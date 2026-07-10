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
from typing import Dict, List, Tuple

from clopt.maxflow import EdmondsKarp
from clopt.model import Network, NodeKind

_BIG = float("inf")


@dataclass
class CutLane:
   src: str
   dst: str
   capacity: float


@dataclass
class TraceStep:
   """One augmentation, in node labels, for hand-trace display."""
   iteration: int
   path: List[str]
   lane_residuals: List[float]                  # the min(...) terms, in path order
   bottleneck: float
   total_after: float
   forward_residual: List[Tuple[str, str, float]]   # lanes with spare capacity
   reverse_residual: List[Tuple[str, str, float]]   # cancellation arcs (the residual trick)
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
      def label(i: int):
         return inv.get(i)  # None for the synthetic super-source/sink

      for k, raw in enumerate(ek.trace, start=1):
         # Strip the synthetic super-source (front) and super-sink (back).
         path_labels = [label(n) for n in raw.path]
         while path_labels and path_labels[0] is None:
               path_labels.pop(0)
         while path_labels and path_labels[-1] is None:
               path_labels.pop()

         fwd: List[Tuple[str, str, float]] = []
         rev: List[Tuple[str, str, float]] = []
         for u, v, cap, is_back in raw.residual_edges:
               lu, lv = label(u), label(v)
               if lu is None or lv is None or cap == _BIG:
                  continue  # skip terminal / super-node arcs
               (rev if is_back else fwd).append((lu, lv, cap))

         used_rev = []
         for u, v in raw.reverse_used:
               lu, lv = label(u), label(v)
               if lu is not None and lv is not None:
                  used_rev.append((lu, lv))

         steps.append(TraceStep(
               iteration=k,
               path=path_labels,
               lane_residuals=raw.lane_residuals,
               bottleneck=raw.bottleneck,
               total_after=raw.total_after,
               forward_residual=sorted(fwd),
               reverse_residual=sorted(rev),
               used_reverse=used_rev,
         ))

   return MaxFlowResult(
      value=value,
      source_side=sorted(source_side),
      cut_lanes=cut_lanes,
      cut_capacity=cut_capacity,
      trace=steps,
   )
