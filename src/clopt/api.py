"""FastAPI surface for the optimizer.

Run with:
    uvicorn clopt.api:app --reload
or via the Makefile / Docker. Interactive docs at /docs.

The API loads *every* dataset in `data/` at startup (plus whatever CLOPT_DATA
names, if that path lives elsewhere) and serves allocation, routing,
Pareto-sweep and naive-plan queries against any of them: each endpoint takes an
optional `dataset` query parameter, defaulting to the CLOPT_DATA dataset.
Loading is eager, so a file that will not load stops the server at start
instead of becoming a mid-class 500 -- see `clopt.datasets`.

/sweep and /naive are a matched pair, and the pairing is load-bearing: they
take the same lambda list with the same default and return entries in the same
order, so the teaching frontend holds two arrays it indexes by one position --
the optimum and the collapse at each lambda. Everything the two share is
declared once here (`LAMBDAS_QUERY`, `_lambda_values`) rather than spelled
twice, because a drift between them puts the naive plan on the projector
beside the wrong optimum: a wrong lecture that looks entirely correct.

The same in-memory `Scenario` is reused; each request applies its threat
picture to a fresh copy, so requests never leak state.
"""

from  __future__ import annotations

import math
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .datasets import DatasetRegistry, build_registry
from .model import Disruption, DisruptionKind, Edge, Node, NodeKind
from .routing import (
   LaneLoad, NaiveConvoy, NaivePlan, SourceLoad,
   cheapest_path, naive_plan, safest_path,
)
from .scenario import Scenario
from .solver import AllocationResult, solve_allocation, pareto_sweep
from .throughput import max_flow_min_cut
from .interdiction import (
   InterdictionTrack, LadderRung,
   budget_interdiction, interdiction_ladder, min_cut_interdiction,
)

app = FastAPI(
   title="Contested-Logistics Routing Optimizer",
   version="0.1.0",
   description="Risk-weighted min-cost-flow resupply planning over a contested network.",
)

# Eager, at import: uvicorn refuses to start on a dataset that will not load,
# and the traceback names the file.
_registry: DatasetRegistry = build_registry()

DATASET_QUERY = Query(None, description="Dataset id (filename stem); omit for the default.")

# One declaration, shared by /sweep and /naive. The frontend prefetches both and
# then holds two arrays it indexes by the same position, so the parameter name
# and the default must be *the same object*, not two literals that agree today.
LAMBDAS_QUERY = Query(
   "0,1,2,5,10,25,50,100",
   description="Comma-separated lambda values; one entry each, plan included.",
)


def get_registry() -> DatasetRegistry:
   return _registry


def use_registry(registry: DatasetRegistry) -> DatasetRegistry:
   """Swap the served registry, returning the previous one.

   The seam a test uses to serve a hand-built theater without reimporting
   this module or reaching for the environment.
   """
   global _registry
   previous = _registry
   _registry = registry
   return previous


def _scenario_for(dataset: Optional[str]) -> Scenario:
   try:
      return get_registry().scenario(dataset)
   except KeyError as exc:
      raise HTTPException(status_code=404, detail=str(exc.args[0]))


def _net_for(dataset: Optional[str], threat: Optional[str]):
   sc = _scenario_for(dataset)
   try:
      return sc.under(threat)
   except KeyError as exc:
      # `str(KeyError)` is the message's *repr*, quotes and all; unwrap it so
      # an unknown threat and an unknown dataset read the same way in JSON.
      raise HTTPException(status_code=404, detail=str(exc.args[0]))


def _lambda_values(lambdas: str) -> List[float]:
   """Parse a `LAMBDAS_QUERY` list, or 400."""
   try:
      return [float(x) for x in lambdas.split(",")]
   except ValueError:
      raise HTTPException(status_code=400, detail="lambdas must be comma-separated numbers.")


# ---- response models --------------------------------------------------------
class Leg(BaseModel):
   src: str
   dst: str
   flow: float
   cost: float
   risk: float


def _legs(res: AllocationResult) -> List[Leg]:
   """The moving legs of a solved allocation, in wire form.

   Shared by /allocate and /sweep so the prefetched row and the one-lambda
   call cannot drift into describing the same plan two different ways.
   """
   return [Leg(src=l.src, dst=l.dst, flow=l.flow, cost=l.cost, risk=l.risk)
           for l in res.active_legs()]


class AllocationResponse(BaseModel):
   risk_aversion: float
   delivered: float
   total_demand: float
   fill_rate: float
   transit_cost: float
   risk_exposure: float
   blended_cost: float
   legs: List[Leg]


class RouteResponse(BaseModel):
   found: bool
   mode: str
   path: List[str]
   hops: int
   total_cost: float
   survival: float


class SweepRow(BaseModel):
   """One lambda's optimum, scalars *and* plan.

   The row carries the legs it describes rather than the scalars alone, so the
   teaching frontend can prefetch the whole frontier and then answer a keypress
   without a fetch. The cost, stated so it is not read as a regression: /sweep
   is no longer a cheap summary call -- it is everything about the optimum at
   each lambda, and a direct API user pays for the plans as well.
   """

   risk_aversion: float
   fill_rate: float
   transit_cost: float
   risk_exposure: float
   legs: List[Leg]


class NaiveConvoyOut(BaseModel):
   """One demand node's resupply, routed as if it were the only one."""

   dst: str
   origin: str   # "" when nothing reaches this destination
   quantity: float
   path: List[str]
   # `null`, not infinity, when `found` is false. The core says INF, which is
   # the honest answer to "what does an impossible convoy cost", but `Infinity`
   # is not JSON -- `JSON.parse` throws on it and the browser loses the whole
   # response rather than one cell. The CLI's `--json` keeps INF: a terminal
   # reader is better served by the honest value. See `_finite_or_null`.
   total_cost: Optional[float]
   total_effective: Optional[float]
   survival: float
   found: bool


class LaneLoadOut(BaseModel):
   """What the superimposed convoys ask of one directed lane, against its cap.

   `over` and `overage` are properties in the core and plain fields here: the
   frontend colours a lane from them, and recomputing `load > cap` in
   JavaScript is how a rounding difference puts a red lane on the projector
   that the API does not agree is red.
   """

   src: str
   dst: str
   load: float
   cap: float
   over: bool
   overage: float


class SourceLoadOut(BaseModel):
   """What one hub is asked to dispatch, against what it actually holds."""

   id: str
   dispatched: float
   stock: float
   over: bool
   overage: float


class NaivePlanRow(BaseModel):
   """One lambda's naive plan, complete.

   *Complete*, not a delta against the lambda before it: a delta format saves
   bytes on a payload measured in kilobytes and buys a reconstruction step the
   frontend can get wrong. The `SweepRow` counterpart is described on `naive`.
   """

   risk_aversion: float
   convoys: List[NaiveConvoyOut]   # exactly one per demand node, always
   lanes: List[LaneLoadOut]        # loaded lanes only
   sources: List[SourceLoadOut]    # every supply node, idle ones included
   notional_cost: float
   unserved: float


class DatasetSummary(BaseModel):
   id: str
   name: str
   description: str


# The `/scenario` payload. Unlike the result endpoints, which report the
# outcome of a solve, this is a *contract* -- the frontend draws from it -- so
# it is modelled rather than hand-built as a dict, and /docs documents it.
class NodeOut(BaseModel):
   id: str
   # The enum, not a bare `str`: it costs nothing and makes /docs list the
   # kinds a client can expect instead of promising "any string".
   kind: NodeKind
   quantity: float
   label: str
   # Authored diagram position in `viewBox` units, `null` when unauthored.
   # Both or neither -- enforced in `Node.__post_init__`, so a half-authored
   # file stops the server at startup rather than reaching this model.
   x: Optional[float] = None
   y: Optional[float] = None


class EdgeOut(BaseModel):
   """One *stored* edge -- never a reverse arc.

   A bidirectional lane is one entry here and two arcs in the solver. Shipping
   the expansion would draw the lane twice and would give an interdiction
   result an entry meaning "this arc" when the model's truth is "both arcs".
   The frontend derives reverses from `bidirectional`.
   """

   # The stored-edge index, zero-padded: the file's edge order is the
   # contract. An index rather than a "src>dst" composite because the model
   # permits parallel edges, which a composite would not distinguish.
   id: str
   src: str
   dst: str
   cap: float
   cost: float
   risk: float
   bidirectional: bool


class NetworkOut(BaseModel):
   nodes: List[NodeOut]
   edges: List[EdgeOut]


class DisruptionOut(BaseModel):
   """A threat picture's declaration, as authored.

   Ships alongside the computed `changes` because `note` is instructor-written
   narration that nothing in the repo has ever rendered -- on a projector it
   is the caption.
   """

   kind: DisruptionKind
   src: Optional[str] = None
   dst: Optional[str] = None
   node: Optional[str] = None
   factor: float
   value: float
   note: str


class EdgeChangeOut(BaseModel):
   """The post-disruption state of one stored edge, keyed by its edge id."""

   id: str
   cap: float
   risk: float


class ThreatPictureOut(BaseModel):
   disruptions: List[DisruptionOut]
   # Server-computed, and deliberately redundant with the declarations above:
   # the alternative is the frontend reimplementing five disruption kinds in
   # JavaScript, including remove-node's zero-every-incident-edge semantics
   # and a risk clamp. A divergence there puts a capacity on the projector
   # that the API disagrees with, mid-class, with nothing raised anywhere.
   changes: List[EdgeChangeOut]


class ScenarioResponse(BaseModel):
   name: str
   description: str
   # Named `node_count`/`edge_count`, not `nodes`/`edges`: those keys now hold
   # the arrays inside `network`, and one key cannot mean both an integer and
   # a list.
   node_count: int
   edge_count: int
   total_supply: float
   total_demand: float
   network: NetworkOut
   threat_pictures: Dict[str, ThreatPictureOut]


def _edge_id(index: int) -> str:
   """The stored-edge index as an id.

   Zero-padded to two digits, which keeps ids the same width -- and so
   lexically ordered -- on every dataset the unit ships. A file with more
   than a hundred edges would widen and lose that; nothing draws such a
   theater, and the id remains unique and contiguous regardless.
   """
   return f"e{index:02d}"


def _node_out(node: Node) -> NodeOut:
   return NodeOut(id=node.id, kind=node.kind, quantity=node.quantity,
                  label=node.label, x=node.x, y=node.y)


def _edge_out(index: int, edge: Edge) -> EdgeOut:
   return EdgeOut(id=_edge_id(index), src=edge.src, dst=edge.dst, cap=edge.cap,
                  cost=edge.cost, risk=edge.risk, bidirectional=edge.bidirectional)


def _disruption_out(disruption: Disruption) -> DisruptionOut:
   return DisruptionOut(kind=disruption.kind, src=disruption.src,
                        dst=disruption.dst, node=disruption.node,
                        factor=disruption.factor, value=disruption.value,
                        note=disruption.note)


def _finite_or_null(value: float) -> Optional[float]:
   """A cost, or `null` where the core says infinity. See `NaiveConvoyOut`.

   Pydantic's serializer would also render a non-finite float as `null`, but
   that is a library default (`ser_json_inf_nan`) rather than something this
   module promises. Converting here puts the wire contract in the code that
   owns it, and a config flip elsewhere cannot quietly ship `Infinity`.
   """
   return value if math.isfinite(value) else None


def _convoy_out(convoy: NaiveConvoy) -> NaiveConvoyOut:
   return NaiveConvoyOut(
      dst=convoy.dst, origin=convoy.origin, quantity=convoy.quantity,
      path=convoy.path, total_cost=_finite_or_null(convoy.total_cost),
      total_effective=_finite_or_null(convoy.total_effective),
      survival=convoy.survival, found=convoy.found,
   )


def _lane_load_out(lane: LaneLoad) -> LaneLoadOut:
   return LaneLoadOut(src=lane.src, dst=lane.dst, load=lane.load, cap=lane.cap,
                      over=lane.over, overage=lane.overage)


def _source_load_out(source: SourceLoad) -> SourceLoadOut:
   return SourceLoadOut(id=source.id, dispatched=source.dispatched,
                        stock=source.stock, over=source.over,
                        overage=source.overage)


def _naive_plan_out(plan: NaivePlan) -> NaivePlanRow:
   return NaivePlanRow(
      risk_aversion=plan.risk_aversion,
      convoys=[_convoy_out(c) for c in plan.convoys],
      lanes=[_lane_load_out(l) for l in plan.lanes],
      sources=[_source_load_out(s) for s in plan.sources],
      notional_cost=plan.notional_cost,
      unserved=plan.unserved,
   )


def _threat_picture_out(sc: Scenario, name: str) -> ThreatPictureOut:
   return ThreatPictureOut(
      disruptions=[_disruption_out(d) for d in sc.threat_pictures[name]],
      changes=[
         EdgeChangeOut(id=_edge_id(c.index), cap=c.cap, risk=c.risk)
         for c in sc.edge_changes(name)
      ],
   )


# ---- endpoints --------------------------------------------------------------
@app.get("/health")
def health() -> dict:
   return {"status": "ok"}


@app.get("/datasets", response_model=List[DatasetSummary])
def datasets() -> List[DatasetSummary]:
   """The dataset menu, in cycle order: default first, then alphabetical."""
   return [DatasetSummary(**row) for row in get_registry().summaries()]


@app.get("/scenario", response_model=ScenarioResponse)
def scenario(dataset: Optional[str] = DATASET_QUERY) -> ScenarioResponse:
   """The whole drawable payload: the network, and every threat picture's effects.

   There is no `threat` parameter -- the pristine network is returned always,
   and the effects of each picture ship inside `threat_pictures`. One request
   gives a frontend everything it needs to draw the theater and to switch
   between threat pictures without asking again.
   """
   sc = _scenario_for(dataset)
   net = sc.network
   return ScenarioResponse(
      name=sc.name,
      description=sc.description,
      node_count=len(net.nodes),
      edge_count=len(net.edges),
      total_supply=net.total_supply(),
      total_demand=net.total_demand(),
      network=NetworkOut(
         nodes=[_node_out(n) for n in net.nodes.values()],
         # `net.edges`, not `net.directed_edges()`: the stored edges are the
         # contract, and the expansion is the solver's business.
         edges=[_edge_out(i, e) for i, e in enumerate(net.edges)],
      ),
      threat_pictures={
         name: _threat_picture_out(sc, name) for name in sc.threat_pictures
      },
   )


@app.get("/allocate", response_model=AllocationResponse)
def allocate(
   risk_aversion: float = Query(0.0, ge=0.0, description="Cost/risk trade dial (lambda)."),
   threat: Optional[str] = Query(None, description="Named threat picture."),
   dataset: Optional[str] = DATASET_QUERY,
) -> AllocationResponse:
   res = solve_allocation(_net_for(dataset, threat), risk_aversion=risk_aversion)
   return AllocationResponse(
      risk_aversion=res.risk_aversion,
      delivered=res.delivered,
      total_demand=res.total_demand,
      fill_rate=res.fill_rate,
      transit_cost=res.transit_cost,
      risk_exposure=res.risk_exposure,
      blended_cost=res.blended_cost,
      legs=_legs(res),
   )


@app.get("/route", response_model=RouteResponse)
def route(
   src: str = Query(..., alias="from", description="Origin node id."),
   dst: str = Query(..., alias="to", description="Destination node id."),
   risk_aversion: float = Query(0.0, ge=0.0),
   safest: bool = Query(False, description="Maximize survival intead of minimizing cost."),
   threat: Optional[str] = Query(None),
   dataset: Optional[str] = DATASET_QUERY,
) -> RouteResponse:
   net = _net_for(dataset, threat)
   if src not in net.nodes or dst not in net.nodes:
      raise HTTPException(status_code=404, detail="Unknown node id.")
   if safest:
      r = safest_path(net, src, dst)
      mode = "safest"
   else:
      r = cheapest_path(net, src, dst, risk_aversion=risk_aversion)
      mode = "cheapest"
   return RouteResponse(
      found=r.found, mode=mode, path=r.path, hops=r.hops,
      total_cost=r.total_cost, survival=r.survival,
   )


@app.get("/sweep", response_model=List[SweepRow])
def sweep(
   lambdas: str = LAMBDAS_QUERY,
   threat: Optional[str] = Query(None),
   dataset: Optional[str] = DATASET_QUERY,
) -> List[SweepRow]:
   results = pareto_sweep(_net_for(dataset, threat), _lambda_values(lambdas))
   return [
      SweepRow(risk_aversion=r.risk_aversion, fill_rate=r.fill_rate,
               transit_cost=r.transit_cost, risk_exposure=r.risk_exposure,
               legs=_legs(r))
      for r in results
   ]


@app.get("/naive", response_model=List[NaivePlanRow])
def naive(
   lambdas: str = LAMBDAS_QUERY,
   threat: Optional[str] = Query(None),
   dataset: Optional[str] = DATASET_QUERY,
) -> List[NaivePlanRow]:
   """Day 1's counterexample, one complete plan per lambda.

   The mirror of /sweep: same parameter, same default, same order, so the two
   responses are arrays a frontend indexes by the same position -- /sweep for
   the optimum, /naive for the collapse -- and the A/B flip is a swap at one
   index rather than a reconciliation.

   Stateless and complete. The whole array ships in one call because the
   frontend renders synchronously and a keypress can never await a fetch, and
   each entry is a whole plan rather than a delta against the entry before it.
   """
   net = _net_for(dataset, threat)
   return [
      _naive_plan_out(naive_plan(net, risk_aversion=value))
      for value in _lambda_values(lambdas)
   ]


@app.get("/maxflow")
def maxflow(
   threat: Optional[str] = Query(None),
   dataset: Optional[str] = DATASET_QUERY,
) -> dict:
   res = max_flow_min_cut(_net_for(dataset, threat))
   return {
      "max_throughput": res.value,
      "cut_capacity": res.cut_capacity,
      "source_side": res.source_side,
      "cut_lanes": [{"src": c.src, "dst": c.dst, "capacity": c.capacity}
                     for c in res.cut_lanes],
   }


def _track_out(track: InterdictionTrack) -> dict:
   return {
      "method": track.method,
      "removed": [{"src": s, "dst": d} for s, d in track.removed],
      "residual_throughput": track.residual_throughput,
      # `searched` and `skipped`, never "subsets considered". The space's size
      # is the rung's `subsets_total`; saying a greedy track "considered" it is
      # a claim about work greedy declined to do, and the declining is the
      # lesson. See `interdiction.BudgetInterdiction`.
      "searched": track.searched,
      "skipped": track.skipped,
   }


def _rung_out(rung: LadderRung) -> dict:
   return {
      "k": rung.k,
      "k_through": rung.k_through,
      "exhaustive": _track_out(rung.exhaustive),
      "greedy": _track_out(rung.greedy),
      "subsets_total": rung.subsets_total,
      "diverges": rung.diverges,
   }


@app.get("/interdict")
def interdict(
   budget: Optional[int] = Query(None, ge=1,
                                 description="Max lanes to remove; omit for min-cut interdiction. "
                                             "In ladder mode, the ceiling on k."),
   method: str = Query("auto", pattern="^(auto|exhaustive|greedy)$"),
   ladder: bool = Query(False,
                        description="Walk k=1.. with both methods at every rung "
                                    "(Day 4). Ignores `method`; see below."),
   threat: Optional[str] = Query(None),
   dataset: Optional[str] = DATASET_QUERY,
) -> dict:
   """Three modes, and the third is the teaching one.

   No `budget`: min-cut interdiction. With `budget`: one search at one k, the
   shape the CLI prints -- unchanged, and it stays unchanged. With
   `ladder=true`: rungs k=1.. carrying *both* methods, terminating where both
   reach zero, each rung flagged `diverges` by the server.

   The ladder is one call per dataset rather than the 2 x K x datasets the
   frontend would otherwise issue at boot, and -- the reason it lives on the
   server at all -- termination and the identical-rung collapse become facts a
   test can pin instead of logic in a render pass.
   """
   net = _net_for(dataset, threat)
   if ladder:
      if method != "auto":
         # Not ignored: a ladder runs both methods by definition, so there is
         # nothing for `method` to select, and silently accepting it would let
         # a caller believe it had asked for a one-method ladder and got one.
         raise HTTPException(
            status_code=400,
            detail="ladder mode runs both methods; drop the `method` parameter.",
         )
      # `budget` is the ceiling here, not the answer. Omitted, the core's
      # default guard applies and the data decides where the ladder stops.
      kwargs = {} if budget is None else {"max_budget": budget}
      result = interdiction_ladder(net, **kwargs)
      return {
         "mode": "ladder",
         "baseline_throughput": result.baseline_throughput,
         "min_cut_capacity": result.min_cut_capacity,
         # False when the ceiling cut the ladder short: a truncated ladder must
         # not be read as "and then the network was severed".
         "terminated": result.terminated,
         "rungs": [_rung_out(r) for r in result.rungs],
      }
   if budget is None:
      inter = min_cut_interdiction(net)
      return {
         "mode": "min_cut",
         "baseline_throughput": inter.baseline_throughput,
         "cut_capacity": inter.cut_capacity,
         "cut_lanes": [{"src": c.src, "dst": c.dst, "capacity": c.capacity}
                        for c in inter.cut_lanes],
      }
   res = budget_interdiction(net, budget=budget, method=method)
   return {
      "mode": "budget",
      "method": res.method,
      "budget": res.budget,
      "baseline_throughput": res.baseline_throughput,
      "residual_throughput": res.residual_throughput,
      "removed": [{"src": s, "dst": d} for s, d in res.removed],
      "subsets_considered": res.subsets_considered,
      "min_cut_capacity": res.min_cut_capacity,
   }
