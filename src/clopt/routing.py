"""Single-commodity routing queries on a `Network`.

`MinCostFlow` answers the *allocation* question -- how should the whole theater
move stock from many sources to many sinks. Sometimes you just want the
*routing* question for one convoy: what is the best single path from A to B?

Two notions of "best" are offered:

1. cheapest_path  -- minimize sum of effective edge weights
                     (cost + lambda * risk). Additive, so plain Dijkstra.
2. safest_path    -- maximize probability of arriving intact, treating each
                     edge's risk as an independent interdiction probability.
                     Survival multiplies along a path; we maximize the product
                     by minimizing the sum of -log(1 - risk), which is again a
                     shortest-path problem. This is the multiplicative model the
                     allocation solver deliberately avoids (it is nonlinear in
                     flow), but for a single path it is exact and cheap.

And then there is `naive_plan`, which is what happens when you try to build a
theater-wide *plan* out of nothing but cheapest-path *queries*. Serve every
destination from its own cheapest origin, superimpose the routes, and count:
lanes carry more than they can hold and hubs dispatch stock they do not have.
It lives here, next to the query it misuses, because the adjacency is the
lesson -- filed in a module of its own it would be a counterexample with
nothing to be a counterexample to.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .model import Network

INF  = float("inf")

@dataclass
class PathResult:
   path: List[str]
   total_cost: float       # sum of raw transit cost along the path
   total_effective: float  # sum of (cost + lambda*risk)
   survival: float         # product of (1 - risk) along the path, in [0,1]
   found: bool = True

   @property
   def hops(self) -> int:
      return max(0, len(self.path) - 1)


def _adjacency(net: Network) -> Dict[str, List[Tuple[str, float, float]]]:
   """Build src -> [(dst, cost, risk)] over usable (cap > 0) directed edges"""
   adj: Dict[str, List[Tuple[str, float, float]]] = {nid: [] for nid in net.nodes}
   for e in net.directed_edges():
      if e.cap > 0:
         adj[e.src].append((e.dst, e.cost, e.risk))
   return adj


def _dijkstra(
      net: Network,
      source: str,
      target: str,
      weight,
) -> Optional[List[str]]:
   """Generic Dijkstra returning the node path, or None if unreachable.

   `weight(cost, risk)` maps an edge to a non-negative scalar.
   """
   if source not in net.nodes or target not in net.nodes:
      raise KeyError("Source/target must be nodes in the network")
   adj = _adjacency(net)
   dist: Dict[str, float] = {nid: INF for nid in net.nodes}
   prev: Dict[str, Optional[str]] = {nid: None for nid in net.nodes}
   dist[source] = 0.0
   pq: List[Tuple[float, str]] = [(0.0, source)]
   done = set()
   while pq:
      d, u = heapq.heappop(pq)
      if u in done:
         continue
      done.add(u)
      if u == target:
         break
      for v, cost, risk in adj[u]:
         nd = d + weight(cost, risk)
         if nd < dist[v]:
            dist[v] = nd
            prev[v] = u
            heapq.heappush(pq, (nd, v))
   if dist[target] == INF:
      return None
   # Reconstruct the path
   path = [target]
   while path[-1] != source:
      p = prev[path[-1]]
      if p is None:
         return None
      path.append(p)
   path.reverse()
   return path


def _summarize(net: Network, path: List[str], risk_aversion: float) -> PathResult:
   # Resolve the actual edges used (pick the cheapest-effective parallel edge)
   by_pair: Dict[Tuple[str, str], Tuple[float, float]] = {}
   for e in net.directed_edges():
      if e.cap <= 0:
         continue
      key = (e.src, e.dst)
      eff = e.effective_cost(risk_aversion)
      if key not in by_pair or eff < by_pair[key][0] + risk_aversion * by_pair[key][1]:
         by_pair[key] = (e.cost, e.risk)
   total_cost = 0.0
   total_eff = 0.0
   survival = 1.0
   for u, v in zip(path, path[1:]):
      cost, risk = by_pair[(u, v)]
      total_cost += cost
      total_eff += cost + risk_aversion * risk
      survival *= (1.0 - risk)
   return PathResult(path, total_cost, total_eff, survival, found=True)


def cheapest_path(net: Network, source: str, target: str, risk_aversion: float = 0.0) -> PathResult:
    """Lowest combined cost path under effective weight cost + lambda*risk."""
    path = _dijkstra(net, source, target, lambda c, r: c + risk_aversion * r)
    if path is None:
        return PathResult([], INF, INF, 0.0, found=False)
    return _summarize(net, path, risk_aversion)


def safest_path(net: Network, source: str, target: str) -> PathResult:
   """Maximize survival probability = product of (1 - risk) along the path.

   Implemented as a shortest path on weight -log(1 - risk). An edge with
   risk = 1 is impassable for this query (infinite weight).
   """
   def weight(_cost: float, risk:float) -> float:
      if risk >= 1.0:
         return INF
      return -math.log(1.0 - risk)
   
   path = _dijkstra(net, source, target, weight)
   if path is None:
      return PathResult([], INF, INF, 0.0, found=False)
   return _summarize(net, path, risk_aversion=0.0)


# --------------------------------------------------------------------------
# The naive plan: what cheapest-path queries add up to, and why that fails.
# --------------------------------------------------------------------------

@dataclass
class NaiveConvoy:
   """One demand node's resupply, routed as if it were the only one."""

   dst: str                # the demand node being served
   origin: str             # the supply node chosen ("" if nothing reaches it)
   quantity: float         # the demand, moved in full -- no rationing here
   path: List[str]
   total_cost: float       # per-unit raw transit cost along the path
   total_effective: float  # per-unit cost + lambda*risk
   survival: float
   found: bool = True

   @property
   def hops(self) -> int:
      return max(0, len(self.path) - 1)


@dataclass
class LaneLoad:
   """How much the superimposed convoys ask of one directed lane.

   Keyed by `(src, dst)` rather than an edge id: convoys know the nodes they
   pass through, and parallel edges between the same pair are one lane as far
   as "can this move?" is concerned.
   """

   src: str
   dst: str
   load: float
   cap: float

   @property
   def over(self) -> bool:
      # Strict. A lane loaded exactly to capacity is a lane doing its job,
      # and drawing it red would cost the violation colour its meaning.
      return self.load > self.cap

   @property
   def overage(self) -> float:
      return max(0.0, self.load - self.cap)


@dataclass
class SourceLoad:
   """How much one hub is asked to dispatch, against what it actually holds."""

   id: str
   dispatched: float
   stock: float

   @property
   def over(self) -> bool:
      return self.dispatched > self.stock

   @property
   def overage(self) -> float:
      return max(0.0, self.dispatched - self.stock)


@dataclass
class NaivePlan:
   risk_aversion: float
   convoys: List[NaiveConvoy]   # exactly one per demand node
   lanes: List[LaneLoad]        # loaded lanes only
   sources: List[SourceLoad]    # every supply node, idle ones included
   notional_cost: float         # the price of a plan you cannot execute
   unserved: float


def _lane_caps(net: Network) -> Dict[Tuple[str, str], float]:
   """Capacity available on each directed pair, summing parallel edges."""
   caps: Dict[Tuple[str, str], float] = {}
   for e in net.directed_edges():
      if e.cap > 0:
         caps[(e.src, e.dst)] = caps.get((e.src, e.dst), 0.0) + e.cap
   return caps


def naive_plan(net: Network, risk_aversion: float = 0.0) -> NaivePlan:
   """Serve each demand node from its globally cheapest origin, then count.

   This is the plan a room proposes out loud on Day 1, and it is unbuildable.
   Each destination is routed independently: no convoy knows what its siblings
   committed, and no hub is asked whether it has the stock. Superimposing the
   routes is what surfaces the two failures -- lanes carrying more than their
   capacity, and hubs dispatching past their inventory.

   The assignment rule is naive *on purpose*. Anything smarter (round-robin,
   stock-aware) partially repairs the plan and blunts the lesson; the point is
   a collapse that the room can see coming and still not prevent by routing.

   Ties break on `(effective_cost, origin_id)`. Falling back to JSON key order
   would mean re-ordering the nodes array silently moved a convoy.

   Note `notional_cost`: it is raw transit cost summed over convoys, and it
   undercuts the feasible optimum precisely because it is buying capacity that
   does not exist. It is named to carry its own asterisk.
   """
   supplies = sorted(net.supply_nodes(), key=lambda n: n.id)
   caps = _lane_caps(net)

   convoys: List[NaiveConvoy] = []
   loads: Dict[Tuple[str, str], float] = {}
   dispatched: Dict[str, float] = {n.id: 0.0 for n in supplies}
   notional = 0.0
   unserved = 0.0

   for demand in sorted(net.demand_nodes(), key=lambda n: n.id):
      best: Optional[Tuple[str, PathResult]] = None
      for origin in supplies:
         r = cheapest_path(net, origin.id, demand.id, risk_aversion)
         if not r.found:
            continue
         # `supplies` is already id-sorted, so a strict `<` keeps the
         # lowest id among equals -- the (effective_cost, origin_id) rule.
         if best is None or r.total_effective < best[1].total_effective:
            best = (origin.id, r)

      if best is None:
         # Unreachable demand is a convoy that failed, not a missing row:
         # the convoy count equals the demand-node count either way, so a
         # reader (or a frontend) never reconciles two lists.
         convoys.append(NaiveConvoy(
            dst=demand.id, origin="", quantity=demand.quantity, path=[],
            total_cost=INF, total_effective=INF, survival=0.0, found=False,
         ))
         unserved += demand.quantity
         continue

      origin_id, r = best
      convoys.append(NaiveConvoy(
         dst=demand.id, origin=origin_id, quantity=demand.quantity,
         path=r.path, total_cost=r.total_cost,
         total_effective=r.total_effective, survival=r.survival, found=True,
      ))
      notional += demand.quantity * r.total_cost
      dispatched[origin_id] += demand.quantity
      for u, v in zip(r.path, r.path[1:]):
         loads[(u, v)] = loads.get((u, v), 0.0) + demand.quantity

   lanes = [
      LaneLoad(src=s, dst=d, load=load, cap=caps.get((s, d), 0.0))
      for (s, d), load in sorted(loads.items())
   ]
   sources = [
      SourceLoad(id=n.id, dispatched=dispatched[n.id], stock=n.quantity)
      for n in supplies
   ]
   return NaivePlan(
      risk_aversion=risk_aversion,
      convoys=convoys,
      lanes=lanes,
      sources=sources,
      notional_cost=notional,
      unserved=unserved,
   )
