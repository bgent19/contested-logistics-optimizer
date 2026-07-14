"""FastAPI surface for the optimizer.

Run with:
    uvicorn clopt.api:app --reload
or via the Makefile / Docker. Interactive docs at /docs.

The API loads a scenario file at startup (path from the CLOPT_DATA env var,
defaulting to data/theater_sample.json) and serves allocation, routing, and
Pareto-sweep queries against it. The same in-memory `Scenario` is reused; each
request applies its threat picture to a fresh copy, so requests never leak state.
"""

from  __future__ import annotations

import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .routing import cheapest_path, safest_path
from .scenario import Scenario, load_scenario
from .solver import solve_allocation, pareto_sweep
from .throughput import max_flow_min_cut
from .interdiction import budget_interdiction, min_cut_interdiction

DATA_PATH = os.environ.get("CLOPT_DATA", "data/theater_sample.json")

app = FastAPI(
   title="Contested-Logistics Routing Optimizer",
   version="0.1.0",
   description="Risk-weighted min-cost-flow resupply planning over a contested etwork.",
)

_scenario: Optional[Scenario] = None


def _get_scenario() -> Scenario:
   global _scenario
   if _scenario is None:
      _scenario = load_scenario(DATA_PATH)
   return _scenario


def _net_for(threat: Optional[str]):
   sc = _get_scenario()
   try:
      return sc.under(threat)
   except KeyError as exc:
      raise HTTPException(status_code=404, detail=str(exc))
   

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


# ---- endpoints --------------------------------------------------------------
@app.get("/health")
def health() -> dict:
   return {"status": "ok"}


@app.get("/scenario")
def scenario() -> dict:
   sc = _get_scenario()
   net = sc.network
   return {
      "name": sc.name,
      "description": sc.description,
      "nodes": len(net.nodes),
      "edges": len(net.edges),
      "total_supply": net.total_supply(),
      "total_demand": net.total_demand(),
      "threat_pictures": sorted(sc.threat_pictures),
      }


@app.get("/allocate", response_model=AllocationResponse)
def allocate(
   risk_aversion: float = Query(0.0, ge=0.0, description="Cost/risk trade dial (lambda)."),
   threat: Optional[str] = Query(None, description="Named threat picture."),
) -> AllocationResponse:
   res = solve_allocation(_net_for(threat), risk_aversion=risk_aversion)
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
) -> RouteResponse:
   net = _net_for(threat)
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
) -> List[SweepRow]:
   try:
      values = [float(x) for x in lambdas.split(",")]
   except ValueError:
      raise HTTPException(status_code=400, detail="lambdas must be comma-separated numbers.")
   results = pareto_sweep(_net_for(threat), values)
   return [
      SweepRow(risk_aversion=r.risk_aversion, fill_rate=r.fill_rate,
               transit_cost=r.transit_cost, risk_exposure=r.risk_exposure)
      for r in results
   ]


@app.get("/maxflow")
def maxflow(threat: Optional[str] = Query(None)) -> dict:
   res = max_flow_min_cut(_net_for(threat))
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
) -> dict:
   net = _net_for(threat)
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
