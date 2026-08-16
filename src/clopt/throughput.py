"""Network-level throughput analysis: maximum resupply rate and its witness cut.

Wraps the Edmonds-Karp core for a `Network` by adding a super-source over all
supply nodes and a super-sink over all demand nodes, then reports the answer in
domain terms: how many units per planning window the theater can absorb, and the
minimum-capacity set of lanes whose loss caps it (the adversary's cheapest
capacity-weighted blockade -- the Day 3 certificate).

Terminal arcs (super-source -> supply, demand -> super-sink) are given large
capacity so the cut is always expressed in *lanes*, not in "a hub simply doesn't
hold enough." Throughput is therefore the capacity ceiling of the lane network,
which is exactly the quantity interdiction tries to drive down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .maxflow import EdmondsKarp
from .model import Network, NodeKind

_BIG = float("inf")

# Ids for the two synthetic terminals, which have no node in the scenario file
# and so have no id of their own. Reserved rather than guessed: scenario ids
# are uppercase-hyphen (`HUB-ALPHA`, `STRAIT-3`), so a dunder prefix cannot
# collide with one, and a trace consumer can filter on these by name.
SUPER_SOURCE = "__source__"
SUPER_SINK = "__sink__"


@dataclass
class CutLane:
   src: str
   dst: str
   capacity: float


@dataclass
class TraceStep:
   """One augmentation, in node labels, for hand-trace display.

   Complete and unfiltered, and `iteration` 0 is the graph before the first
   push. Two filters used to run here, both purely to tidy CLI output, and
   both damaged a drawn trace: stripping the synthetic terminals made a route
   appear to begin mid-graph, and dropping the unbounded residual terms
   de-aligned `lane_residuals` from `path`, so a `min(...)` term could no
   longer be anchored to the lane it came from. They now run at print time --
   see `cli.cmd_maxflow` -- and `len(lane_residuals) == len(path) - 1` holds
   on every augmentation.

   `None` residual means unbounded: the terminal arcs are built at infinity.
   """
   iteration: int
   path: List[str]
   lane_residuals: List[Optional[float]]        # the min(...) terms, one per arc of `path`
   bottleneck: float
   total_after: float
   forward_residual: List[Tuple[str, str, Optional[float]]]   # arcs with spare capacity
   reverse_residual: List[Tuple[str, str, Optional[float]]]   # cancellation arcs (the residual trick)
   # Flow on every lane, saturated ones included at their capacity and
   # untouched ones at 0. The residual lists cannot say this: they drop an arc
   # once it saturates, and the saturated lanes are the interesting ones.
   flows: List[Tuple[str, str, float]] = field(default_factory=list)
   used_reverse: List[Tuple[str, str]] = field(default_factory=list)  # reverse arcs this step traversed


@dataclass
class MaxFlowResult:
   value: float                       # max throughput (units / window)
   source_side: List[str]             # node ids on the source side of the cut
   cut_lanes: List[CutLane] = field(default_factory=list)
   cut_capacity: float = 0.0          # = value, by Max-Flow Min-Cut
   trace: List[TraceStep] = field(default_factory=list)


def _build(net: Network) -> Tuple[EdmondsKarp, Dict[str, int], int, int, List[Tuple[int, str, str, float]]]:
   ids = list(net.nodes.keys())
   index = {nid: i for i, nid in enumerate(ids)}
   S = len(ids)
   T = len(ids) + 1
   ek = EdmondsKarp(len(ids) + 2)

   # Terminal arcs: large capacity so cuts land on lanes, not supply limits.
   for node in net.nodes.values():
      if node.kind is NodeKind.SUPPLY and node.quantity > 0:
         ek.add_edge(S, index[node.id], _BIG)
      elif node.kind is NodeKind.DEMAND and node.quantity > 0:
         ek.add_edge(index[node.id], T, _BIG)

   lane_handles: List[Tuple[int, str, str, float]] = []
   for e in net.directed_edges():
      if e.cap <= 0:
         continue
      h = ek.add_edge(index[e.src], index[e.dst], e.cap)
      lane_handles.append((h, e.src, e.dst, e.cap))

   return ek, index, S, T, lane_handles


def _bounded(residual: float) -> Optional[float]:
   """A residual, or `None` where the arc is unbounded.

   The terminal arcs are built at infinity so that cuts land on lanes rather
   than on supply limits, and `Infinity` is not JSON -- `JSON.parse` throws on
   it and a browser loses the whole response rather than one numeral. `None`
   also happens to be the honest thing to draw: a super-source arc should not
   carry a capacity label.
   """
   return None if residual == _BIG else residual


def _arc_order(arc: Tuple[str, str, Optional[float]]):
   """Sort arcs by endpoints, unbounded last -- a `None` will not compare."""
   return (arc[0], arc[1], _BIG if arc[2] is None else arc[2])


def max_flow_min_cut(net: Network, trace: bool = False) -> MaxFlowResult:
   ek, index, S, T, lane_handles = _build(net)
   value = ek.max_flow(S, T, trace=trace)
   reach = ek.min_cut_source_side(S)

   inv = {i: nid for nid, i in index.items()}
   source_side = [inv[i] for i in range(len(index)) if reach[i]]

   crossing = set(ek.crossing_arcs(reach))
   cut_lanes: List[CutLane] = []
   cut_capacity = 0.0
   for h, src, dst, cap in lane_handles:
      if h in crossing:
         cut_lanes.append(CutLane(src, dst, cap))
         cut_capacity += cap

   steps: List[TraceStep] = []
   if trace:
      def label(i: int) -> str:
         if i == S:
            return SUPER_SOURCE
         if i == T:
            return SUPER_SINK
         return inv[i]

      # `enumerate` from 0: `ek.trace[0]` is the before-anything snapshot, so
      # the index *is* the iteration number an instructor says out loud.
      for k, raw in enumerate(ek.trace):
         fwd: List[Tuple[str, str, Optional[float]]] = []
         rev: List[Tuple[str, str, Optional[float]]] = []
         for u, v, cap, is_back in raw.residual_edges:
               (rev if is_back else fwd).append((label(u), label(v), _bounded(cap)))

         steps.append(TraceStep(
               iteration=k,
               path=[label(n) for n in raw.path],
               lane_residuals=[_bounded(c) for c in raw.lane_residuals],
               bottleneck=raw.bottleneck,
               total_after=raw.total_after,
               forward_residual=sorted(fwd, key=_arc_order),
               reverse_residual=sorted(rev, key=_arc_order),
               flows=sorted(((label(u), label(v), f) for u, v, f in raw.flows),
                            key=_arc_order),
               used_reverse=[(label(u), label(v)) for u, v in raw.reverse_used],
         ))

   return MaxFlowResult(
      value=value,
      source_side=sorted(source_side),
      cut_lanes=cut_lanes,
      cut_capacity=cut_capacity,
      trace=steps,
   )
