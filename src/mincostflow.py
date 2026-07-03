"""Minimum-cost flow via Successive Shortest Paths (SSP) with Johnson potentials.

This is the algorithmic. It is written from scratch because the teaching point
was to *show the algorithm*.

The idea
--------
We want to push as much flow as possible (up to a cap) from a source to a sink
at minimum total cost. SSP does this greedily but correctly: repeatedly find the
*cheapest* augmenting path in the residual graph and saturate it. Each such
augmentation preserves the invariant that the current flow is min-cost for its
value, so when we stop we are optimal for the value we shipped.

The wrinkle
-----------
The residual graph has negative-cost arcs (every time you send flow forward you
create a backward arc with cost -c so the algorithm can "undo" it). Plain
Dijkstra can't handle negative edges. Johnson's trick fixes this: maintain a
vertex potential h[v] and search on *reduced costs*

    c'(u, v) = c(u, v) + h[u] - h[v]

which are provably non-negative when the potentials are valid, so Dijkstra is
legal. After each shortest-path computation we update h[v] += dist[v], and the
true cost of the path we just found is exactly h[sink].

Because all *original* edge costs here are non-negative (cost + lambda*risk with
cost, risk >= 0), the initial potentials can simply be zero, so no Bellman-Ford
warm-up needed. I noted where you'd add it if you ever introduced
genuinely negative arcs.

Complexity
----------
Each augmentation runs one Dijkstra in O(E log V). The number of augmentations
is bounded by the number of distinct shortest-path structures; in the worst case
it is O(V * E) for unit-capacity-style graphs, but in practice (and for the
theater sizes here) it is small. With a value target F and integer capacities a
clean bound is O(F * E log V). For the graphs in this repo it returns instantly.
"""

import heapq
from dataclasses import dataclass
from typing import List, Tuple

INF = float('inf')


@dataclass
class _Arc:
   to: int
   cap: float
   cost: float

class MinCostFlow:
   """Integer-indexed min-cost flow solver.

   Build the graph with 'add_edge', then call 'solve'. Arcs are stored in
   consecutive pairs (forward, residual) so the residual of arc 'i' is 'i ^ 1'.
   """

   def __init__(self, num_nodes: int) -> None:
      self.n = num_nodes
      self.arcs: List[_Arc] = []
      self.adj: List[List[int]] = [[] for _ in range(num_nodes)]
      # Remember where each *forward* arc landed so callers can read its flow.
      self._forward_index: List[int] = []

   def add_edge(self, u: int, v: int, cap: float, cost: float) -> int:
      """Add a directed arc u->v with capacity and cost.

      Returns a handle (index into the forward-arc table) that can later be
      passed to `flow_on` to recover how much flow used this arc.
      """
      forward = len(self.arcs)
      self.adj[u].append(forward)
      self.arcs.append(_Arc(v, cap, cost))
      self.adj[v].append(forward + 1)
      self.arcs.append(_Arc(u, 0.0, -cost)) # residual arc, starts empty
      self._forward_index.append(forward)
      return len(self._forward_index) - 1

   def flow_on(self, handle: int) -> float:
      """How much flow ended up on the forward arc identiifed by 'handle'."""
      fwd = self._forward_index[handle]
      # flow pushed forward equals capcity that migrated to the residual arc
      return self.arcs[fwd ^ 1].cap
   
   def solve(self, source: int, sink: int, max_flow: float = INF) -> Tuple[float, float]:
      """Push up to 'max_flow' units from source to sink at minimum cost.

      Returns (flow_shipped, total_cost). If 'max_flow' is INF this is a
      min-cost *max*-flow.
      """
      n = self.n
      h = [0.0] * n # Johnson potentials; zero is valid since costs >= 0.
      # If you ever add negative-cost arcs before the first solve, initialize
      # 'h' with a Bellman-Ford pass from 'source' here.

      total_flow = 0.0
      total_cost = 0.0

      while total_flow < max_flow:
         dist = [INF] * n
         dist[source] = 0.0
         prev_node = [-1] * n
         prev_arc = [-1] * n
         visited = [False] * n
         pq: List[Tuple[float, int]] = [(0.0, source)]

         while pq:
            d, u = heapq.heappop(pq)
            if visited[u]:
               continue
            visited[u] = True
            for arc_id in self.adj[u]:
               arc = self.arcs[arc_id]
               if arc.cap <= 1e-12:
                  continue
               v = arc.to
               # Reduced cost -- non-negative under valid potentials
               nd = d + arc.cost + h[u] - h[v]
               if nd < dist[v] - 1e-12:
                  dist[v] = nd
                  prev_node[v] = u
                  prev_arc[v] = arc_id
                  heapq.heappush(pq, (nd, v))

         if dist[sink] == INF:
            break  # sink unreachable: no more augmenting paths

         # Lift potentials so reduced costs stay valid next round
         for v in range(n):
            if dist[v] < INF:
               h[v] += dist[v]

         # Bottleneck capacity along the discovered path
         push = max_flow - total_flow
         v = sink
         while  v!= source:
            push = min(push, self.arcs[prev_arc[v].cap])
            v = prev_node[v]

         # Augment
         v = sink
         while v != source:
            arc_id = prev_arc[v]
            self.arcs[arc_id].cap -= push
            self.arcs[arc_id ^ 1].cap += push
            v = prev_node[v]

         total_flow += push
         # After the potential lift, h[sink] is the *true* cost of this path
         total_cost += push * h[sink]
         
      return total_flow, total_cost
