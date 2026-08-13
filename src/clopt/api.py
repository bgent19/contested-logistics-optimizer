"""FastAPI surface for the optimizer.

Run with:
    uvicorn clopt.api:app --reload
or via the Makefile / Docker. Interactive docs at /docs.

The API loads *every* dataset in `data/` at startup (plus whatever CLOPT_DATA
names, if that path lives elsewhere) and serves allocation, routing, and
Pareto-sweep queries against any of them: each endpoint takes an optional
`dataset` query parameter, defaulting to the CLOPT_DATA dataset. Loading is
eager, so a file that will not load stops the server at start instead of
becoming a mid-class 500 -- see `clopt.datasets`.

The same in-memory `Scenario` is reused; each request applies its threat
picture to a fresh copy, so requests never leak state.
"""

from  __future__ import annotations

from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, model_validator

from .datasets import DatasetRegistry, build_registry
from .routing import cheapest_path, safest_path
from .scenario import Scenario
from .solver import solve_allocation, pareto_sweep
from .throughput import max_flow_min_cut
from .interdiction import budget_interdiction, min_cut_interdiction

app = FastAPI(
   title="Contested-Logistics Routing Optimizer",
   version="0.1.0",
   description="Risk-weighted min-cost-flow resupply planning over a contested network.",
)

# Eager, at import: uvicorn refuses to start on a dataset that will not load,
# and the traceback names the file.
_registry: DatasetRegistry = build_registry()

DATASET_QUERY = Query(None, description="Dataset id (filename stem); omit for the default.")


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


# ---- response models --------------------------------------------------------
class Leg(BaseModel):
   src: str
   dst: str
   flow: float
   cost: float
   risk: float


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
   risk_aversion: float
   fill_rate: float
   transit_cost: float
   risk_exposure: float


class DatasetSummary(BaseModel):
   id: str
   name: str
   description: str


# The `/scenario` payload. Unlike the result endpoints, which report the
# outcome of a solve, this is a *contract* -- the frontend draws from it -- so
# it is modelled rather than hand-built as a dict, and /docs documents it.
class NodeOut(BaseModel):
   id: str
   kind: str
   quantity: float
   label: str
   # Authored diagram position in `viewBox` units, `null` when unauthored.
   x: Optional[float] = None
   y: Optional[float] = None

   @model_validator(mode="after")
   def _coordinates_are_both_or_neither(self) -> "NodeOut":
      if (self.x is None) != (self.y is None):
         # Half a coordinate is worse than none: a layout cannot place the
         # node and cannot tell that it needs to. Raising here means a file
         # authored that way is caught by the contract test in CI rather
         # than by a 500 in front of a class.
         raise ValueError(
            f"Node {self.id}: x and y must be authored together (got x={self.x}, y={self.y})."
         )
      return self


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

   kind: str
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
   """The stored-edge index as an id. Zero-padded so ids sort as they load."""
   return f"e{index:02d}"


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
         nodes=[
            NodeOut(id=n.id, kind=n.kind.value, quantity=n.quantity,
                    label=n.label, x=n.x, y=n.y)
            for n in net.nodes.values()
         ],
         # `net.edges`, not `net.directed_edges()`: the stored edges are the
         # contract, and the expansion is the solver's business.
         edges=[
            EdgeOut(id=_edge_id(i), src=e.src, dst=e.dst, cap=e.cap,
                    cost=e.cost, risk=e.risk, bidirectional=e.bidirectional)
            for i, e in enumerate(net.edges)
         ],
      ),
      threat_pictures={
         name: ThreatPictureOut(
            disruptions=[
               DisruptionOut(kind=d.kind.value, src=d.src, dst=d.dst,
                             node=d.node, factor=d.factor, value=d.value,
                             note=d.note)
               for d in declarations
            ],
            changes=[
               EdgeChangeOut(id=_edge_id(c.index), cap=c.cap, risk=c.risk)
               for c in sc.edge_changes(name)
            ],
         )
         for name, declarations in sc.threat_pictures.items()
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
      legs=[Leg(src=l.src, dst=l.dst, flow=l.flow, cost=l.cost, risk=l.risk)
            for l in res.active_legs()],
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
   lambdas: str = Query("0,1,2,5,10,25,50,100", description="Comma-separated lambda values."),
   threat: Optional[str] = Query(None),
   dataset: Optional[str] = DATASET_QUERY,
) -> List[SweepRow]:
   try:
      values = [float(x) for x in lambdas.split(",")]
   except ValueError:
      raise HTTPException(status_code=400, detail="lambdas must be comma-separated numbers.")
   results = pareto_sweep(_net_for(dataset, threat), values)
   return [
      SweepRow(risk_aversion=r.risk_aversion, fill_rate=r.fill_rate,
               transit_cost=r.transit_cost, risk_exposure=r.risk_exposure)
      for r in results
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


@app.get("/interdict")
def interdict(
   budget: Optional[int] = Query(None, ge=1,
                                 description="Max lanes to remove; omit for min-cut interdiction."),
   method: str = Query("auto", pattern="^(auto|exhaustive|greedy)$"),
   threat: Optional[str] = Query(None),
   dataset: Optional[str] = DATASET_QUERY,
) -> dict:
   net = _net_for(dataset, threat)
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
