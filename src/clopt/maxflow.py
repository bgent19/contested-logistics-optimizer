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
   """One BFS augmentation, captured for hand-trace / classroom display.

   A *complete snapshot*, not a delta against the step before it: the residual
   graph and every arc's flow are stated in full every time. That is what lets a
   consumer draw step k without having replayed steps 1..k-1, and makes stepping
   backward through a trace an index decrement rather than a re-solve.

   Nothing is filtered out here. `lane_residuals` carries one term per path arc
   including the infinite ones, so it stays index-aligned with `path` and a
   `min(...)` term can be anchored to the arc it came from; a caller that wants
   tidier output narrows it at the point of display.
   """
   path: List[int]                                   # node indices, source..sink
   lane_residuals: List[float]                       # pre-push residual of every path arc
   bottleneck: float
   total_after: float
   residual_edges: List[tuple[int, int, float, bool]]  # (u, v, residual, is_backward) post-push
   flows: List[tuple[int, int, float]] = field(default_factory=list)  # (u, v, flow) per original arc
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
   
   def _snapshot(self, nodes: List[int], pre: List[float], *, bottleneck: float,
                 total: float, rev_used: List[Tuple[int, int]]) -> AugmentationStep:
      """The whole residual graph and every arc's flow, as they stand right now.

      The two floats are keyword-only: `bottleneck` and `total` are the same
      type and adjacent, so transposing them is a silent wrong number rather
      than an error, and it would land on the projector as a plausible trace.
      """
      residual_edges: List[Tuple[int, int, float, bool]] = []
      for idx, arc in enumerate(self.arcs):
         if arc.cap > 1e-12:
            residual_edges.append((self.arcs[idx ^ 1].to, arc.to, arc.cap, idx % 2 == 1))
      # Every original arc, carrying zero where it carries zero. An arc absent
      # from `residual_edges` is saturated, not missing, and only a flow stated
      # for all of them tells those two apart.
      flows = [(self.arcs[fwd ^ 1].to, self.arcs[fwd].to, self.arcs[fwd ^ 1].cap)
               for fwd in self._forward]
      return AugmentationStep(
         path=nodes,
         lane_residuals=pre,
         bottleneck=bottleneck,
         total_after=total,
         residual_edges=residual_edges,
         flows=flows,
         reverse_used=rev_used,
      )

   def max_flow(self, s: int, t: int, trace: bool = False) -> float:
      self.trace = []
      total = 0.0
      if trace:
         # Step 0: the graph before anything is pushed. The first augmentation
         # otherwise has no "before" state to be drawn against, and
         # reconstructing one downstream would mean rebuilding the residual
         # graph outside the solver that owns it.
         self.trace.append(
            self._snapshot([], [], bottleneck=0.0, total=0.0, rev_used=[]))
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
            self.trace.append(self._snapshot(
               nodes, pre, bottleneck=bottleneck, total=total, rev_used=rev_used))
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
