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

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .maxflow import EdmondsKarp
from .model import Network, NodeKind

_BIG = float("inf")

# The super-source and super-sink, named rather than anonymous. A trace that
# strips them shows a route beginning mid-graph across an arc nothing accounts
# for, so they are labelled and shipped. Scenario files use uppercase-hyphen
# ids, so the dunder prefix cannot collide with a real node.
SOURCE_ID = "__source__"
SINK_ID = "__sink__"
SYNTHETIC_IDS = frozenset({SOURCE_ID, SINK_ID})


@dataclass
class CutLane:
   src: str
   dst: str
   capacity: float


@dataclass
class TraceStep:
   """One augmentation, in node labels, for hand-trace display.

   Complete, in the sense the solver's `AugmentationStep` is complete: the
   synthetic terminals are named rather than stripped, and an unbounded residual
   is `None` rather than dropped. `None` means *unbounded*, not unknown -- the
   terminal arcs are built at infinity so that cuts land on lanes, and both JSON
   and a `min(...)` line want something other than `inf` for that.

   Callers that want the tidier classroom form narrow this at display time; see
   `cli.cmd_maxflow`. Filtering here is what de-aligned `lane_residuals` from
   `path` and made a term impossible to anchor to its lane.
   """
   iteration: int                               # 0 is the pre-augmentation snapshot
   path: List[str]
   lane_residuals: List[Optional[float]]        # the min(...) terms, one per hop of `path`
   bottleneck: float
   total_after: float
   forward_residual: List[Tuple[str, str, Optional[float]]]   # lanes with spare capacity
   reverse_residual: List[Tuple[str, str, Optional[float]]]   # cancellation arcs (the residual trick)
   flows: List[Tuple[str, str, float]] = field(default_factory=list)  # every arc, zeros included
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
   """A residual capacity, or `None` where the arc is unbounded."""
   return residual if math.isfinite(residual) else None


def _by_endpoints(arc: Tuple[str, str, float]) -> Tuple[str, str]:
   """Sort arcs by their endpoints alone -- the third field may be `None`."""
   return arc[0], arc[1]


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
      labels = dict(inv)
      labels[S] = SOURCE_ID
      labels[T] = SINK_ID

      def label(i: int) -> str:
         return labels[i]

      # Index 0 is the solver's step 0, so the enumeration index *is* the
      # iteration number the instructor says out loud.
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
               forward_residual=sorted(fwd, key=_by_endpoints),
               reverse_residual=sorted(rev, key=_by_endpoints),
               flows=sorted(((label(u), label(v), f) for u, v, f in raw.flows),
                            key=_by_endpoints),
               used_reverse=[(label(u), label(v)) for u, v in raw.reverse_used],
         ))

   return MaxFlowResult(
      value=value,
      source_side=sorted(source_side),
      cut_lanes=cut_lanes,
      cut_capacity=cut_capacity,
      trace=steps,
   )
