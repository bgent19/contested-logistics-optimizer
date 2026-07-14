"""Maximum flow (Edmonds-Karp) and the min-cut certificate.

This is the Day 2-3 machinery from the unit, implemented to be hand-traceable:
Ford-Fulkerson with BFS-chosen augmenting paths (that BFS choice is what makes it
Edmonds-Karp and gives the O(V * E^2) bound independent of capacities), over an
explicit residual graph that carries backward arcs so earlier decisions can be
undone.

When max-flow terminates it hands you a second thing for free: the set of nodes
still reachable from the source in the residual graph is one side of a minimum
cut, and the original edges crossing that frontier are a *witness* that no larger
flow exists (Max-Flow Min-Cut). Operationally that cut is the interdictor's
cheapest capacity-weighted blockade -- the certificate that can be verified.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

INF  = math.inf


@dataclass
class _Arc:
   to: int
   cap: float          # residual capacity
   orig: float         # original capacity (0 for synthetic backward arcs)


@dataclass
class AugmentationStep:
   """One BFS augmentation, captured for hand-trace / classroom display."""
   path: List[int]                                   # node indices, source..sink
   lane_residuals: List[float]                       # pre-push residual of finite arcs on path
   bottleneck: float
   total_after: float
   residual_edges: List[tuple[int, int, float, bool]]  # (u, v, residual, is_backward) post-push
   reverse_used: List[tuple[int, int]] = field(default_factory=list)  # cancellation arcs traversed


class EdmondsKarp:
   """Integer-indexed max-flow solver with min-cut extraction.

   Arcs are stored in consecutive (forward, backward) pairs, so the residual
   partner of arc `i` is `i ^ 1`.
   """

   def __init__(self, num_nodes: int) -> None:
      self.n = num_nodes
      self.arcs: List[_Arc] = []
      self.adj: List[List[int]] = [[] for _ in range(num_nodes)]
      self._forward: List[int] = []
      self.trace: List[AugmentationStep] = []

   def add_edge(self, u: int, v: int, cap: float) -> int:
      fwd = len(self.arcs)
      self.adj[u].append(fwd)
      self.arcs.append(_Arc(v, cap, cap))
      self.adj[v].append(fwd ^ 1)
      self.arcs.append(_Arc(u, 0.0, 0.0))
      self._forward.append(fwd)
      return len(self._forward) - 1
   
   def flow_on(self, handle: int) -> float:
      fwd = self._forward[handle]
      # Flow equals capacity migrated onto the backward partner arc.
      return self.arcs[fwd ^ 1].cap
   
   def _bfs_augmenting_path(self, s: int, t: int) -> Optional[List[int]]:
      """Return the arc ids of a shortest (fewest-arc) s->t augmenting path."""
      parent_arc = [-1] * self.n
      seen = [False] * self.n
      seen[s] = True
      q = deque([s])
      while q:
         u = q.popleft()
         if u == t:
            break
         for arc_id in self.adj[u]:
            arc = self.arcs[arc_id]
            if arc.cap > 1e-12 and not seen[arc.to]:
               seen[arc.to] = True
               parent_arc[arc.to] = arc_id
               q.append(arc.to)
      if not seen[t]:
         return None
      path: List[int] = []
      v = t
      while v != s:
         a = parent_arc[v]
         path.append(a)
         v = self.arcs[a ^ 1].to  # tail of arc a
      path.reverse()
      return path
   
   def max_flow(self, s: int, t: int, trace: bool = False) -> float:
      self.trace = []
      total = 0.0
      while True:
         path = self._bfs_augmenting_path(s, t)
         if path is None:
            break
         bottleneck = min(self.arcs[a].cap for a in path)
         if trace:
            pre = [self.arcs[a].cap for a in path]
            nodes = [self.arcs[path[0] ^ 1].to] + [self.arcs[a].to for a in path]
            # A path arc with an odd index is a backward (cancellation) arc.
            rev_used = [(self.arcs[a ^ 1].to, self.arcs[a].to)
                        for a in path if a % 2 == 1]
         for a in path:
            self.arcs[a].cap -= bottleneck
            self.arcs[a ^ 1].cap += bottleneck
         total += bottleneck
         if trace:
            residual_edges: List[Tuple[int, int, float, bool]] = []
            for idx, arc in enumerate(self.arcs):
               if arc.cap > 1e-12:
                  u = self.arcs[idx ^ 1].to
                  v = arc.to
                  residual_edges.append((u, v, arc.cap, idx % 2 == 1))
            self.trace.append(AugmentationStep(
               path=nodes,
               lane_residuals=[c for c in pre if c != INF],
               bottleneck=bottleneck,
               total_after=total,
               residual_edges=residual_edges,
               reverse_used=rev_used,
            ))
      return total
   
   def min_cut_source_side(self, s: int) -> List[bool]:
      """Nodes reachable from s in the residual graph after max-flow.
      
      This set S (with T = everything else) is a minimum cut.
      """
      reach = [False] * self.n
      reach[s] = True
      q = deque([s])
      while q:
         u = q.popleft()
         for arc_id in self.adj[u]:
            arc = self.arcs[arc_id]
            if arc.cap > 1e-12 and not reach[arc.to]:
               reach[arc.to] = True
               q.append(arc.to)
      return reach
   
   def crossing_arcs(self, reach: List[bool]) -> List[int]:
      """Handles of forward arcs that cross the cut (tail in S, head in T)."""
      out: List[int] = []
      for h, fwd in enumerate(self._forward):
         arc = self.arcs[fwd]
         tail = self.arcs[fwd ^ 1].to
         if reach[tail] and not reach[arc.to]:
            out.append(h)
      return out  
