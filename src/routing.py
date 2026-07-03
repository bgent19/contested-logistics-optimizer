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
