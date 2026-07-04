"""High-level allocation: turn a `Network` into a min-cost flow problem, solve it,
and report results in domain terms (fill rate, cost, risk exposure, per-leg flow).

Construction
------------
We add a super-source S and super-sink T:

    S --(cap = supply_i, cost 0)--> each supply node i
    each demand node j --(cap = demand_j, cost 0)--> T

Every theater edge becomes an arc with capacity `cap` and cost
`cost + lambda * risk`. A min-cost *max*-flow from S to T then ships as much as
capacity allows at the cheapest risk-blended cost. If total supply < total
demand (or disruptions strangle throughput), the max-flow is partial and the
fill rate drops out naturally -- no special-casing required.

Why min-cost flow gives integer allocations: with integer capacities the SSP
algorithm only ever pushes integer bottleneck amounts, so the per-leg plan is
integral. Convenient when "units" are indivisible (pallets, containers).
"""

from dataclasses import dataclass, field
from typing import List, Tuple

from mincostflow import MinCostFlow
from model import Network, NodeKind


@dataclass
class LegFlow:
   src: str
   dst: str
   flow: float
   cost: float
   risk: float


@dataclass
class AllocationResult:
   risk_aversion: float
   delivered: float
   total_demand: float
   total_supply: float
   transit_cost: float
   risk_exposure: float
   blended_cost: float
   legs: List[LegFlow] = field(default_factory=list)

   @property
   def fill_rate(self) -> float:
      return 0.0 if self.total_demand == 0 else self.delivered / self.total_demand
   
   def active_legs(self) -> List[LegFlow]:
      return [l for l in self.legs if l.flow > 1e-9]
   

def solve_allocation(net: Network, risk_aversion: float) -> AllocationResult:
   """Solve the resupply allocation for a given risk-aversion(lambda)"""
   # Map node ids -> coniguous integer indices, plus source/sink.
   ids = list(net.nodes.keys())
   index = {nid: i for i, nid in enumerate(ids)}
   S = len(ids)
   T = len(ids) + 1
   mcf = MinCostFlow(len(ids) + 2)

   # Super-source / super-sink arcs.
   for node in net.nodes.values():
      if node.kind is NodeKind.SUPPLY and node.quantity > 0:
         mcf.add_edge(S, index[node.id], node.quantity, 0.0)
      elif node.kind is NodeKind.DEMAND and node.quantity > 0:
         mcf.add_edge(index[node.id], T, node.quantity, 0.0)

   # Theater arcs, remembering handles so we can read per-leg flow afterward.
   handles: List[Tuple[int, str, str, float, float]] = []
   for e in net.directed_edges():
      if e.cap <= 0:
         continue
      h = mcf.add_edge(index[e.src], index[e.dst], e.cap, e.effective_cost(risk_aversion))
      handles.append((h, e.src, e.dst, e.cost, e.risk))

   delivered, _blended = mcf.solve(S, T)

   legs: List[LegFlow] = []
   tansit_cost = 0.0
   risk_exposure = 0.0
   blended = 0.0
   for h, src, dst, cost, risk in handles:
      f = mcf.flow_on(h)
      if f > 1e-9:
         legs.append(LegFlow(src, dst, f, cost, risk))
         transit_cost += f * cost
         risk_exposure += f * risk
         blended += f * (cost + risk_aversion * risk)

   return AllocationResult(
      risk_aversion=risk_aversion,
      delivered=delivered,
      total_demand=net.total_demand(),
      total_supply=net.total_supply(),
      transit_cost=transit_cost,
      risk_exposure=risk_exposure,
      blended_cost=blended,
      legs=legs
   )


def pareto_sweep(net: Network, lambdas: List[float]) -> List[AllocationResult]:
   """Solve across a range of risk-aversion values to trace the cost/risk frontier.

   There is no single 'optimal' plan, there is a
   frontier. Increasing lambda buys safety with cost; the sweep shows the
   exchange rate so the decision-maker can choose a point, not be handed one.
   """
   return [solve_allocation(net, lam) for lam in lambdas]