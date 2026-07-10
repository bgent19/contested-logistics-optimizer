"""Network interdiction -- the Day 4 payoff, including where polynomial breaks.

Two questions, deliberately side by side:

1. min_cut_interdiction -- the *capacity-weighted* interdictor pays a cost equal
   to each lane's capacity and wants to drive throughput to zero. By Max-Flow
   Min-Cut this is exactly the minimum cut, and it is polynomial. The cheapest
   such blockade is the min-cut lane set.

2. budget_interdiction -- the *budget* interdictor may remove at most k lanes,
   regardless of their capacity, and wants to minimize remaining throughput.
   This innocent change makes the problem NP-hard: there is no known way to beat
   searching over which k-subset to remove. We expose both an exhaustive optimum
   (correct, but C(|E|, k) subsets -- the combinatorial cliff made visible) and a
   greedy heuristic (fast, not guaranteed optimal), and report the min-cut value
   as a sanity reference.

The split between (1) and (2) is the unit's big complexity lesson: a small,
operationally reasonable change -- paying per lane instead of per unit of
capacity -- flips a problem from "solved in milliseconds" to "no known efficient
algorithm."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from math import comb
from typing import List, Tuple

from .model import Edge, Network
from .throughput import CutLane, max_flow_min_cut


@dataclass
class MinCutInterdiction:
   baseline_throughput: float
   cut_lanes: List[CutLane]
   cut_capacity: float    # capacity-cost to zero out throughput (= baseline)


def min_cut_interdiction(net: Network) -> MinCutInterdiction:
   res = max_flow_min_cut(net)
   return MinCutInterdiction(
      baseline_throughput=res.value,
      cut_lanes=res.cut_lanes,
      cut_capacity=res.cut_capacity,
   )


@dataclass
class BudgetInterdiction:
   budget: int
   method: str                          # "exhaustive" or "greedy"
   baseline_throughput: float
   residual_throughput: float           # throughput after removing the chosen lanes
   removed: List[Tuple[str, str]]       # lanes removed
   subsets_considered: int              # how big the search was (or would be)
   min_cut_capacity: float              # reference: capacity-weighted min cut


def _throughput_without(net: Network, removed_idx) -> float:
   trial = net.copy()
   for i in removed_idx:
      trial.edges[i].cap = 0.0
   return max_flow_min_cut(trial).value


def budget_interdiction(
   net: Network,
   budget: int,
   method: str = "auto",
   exhaustive_limit: int = 20000,
) -> BudgetInterdiction:
   """Remove at most `budget` lanes to minimize remaining throughput.

   method="auto" runs the exhaustive optimum when the number of candidate
   subsets is small enough, else falls back to the greedy heuristic.
   """
   base = max_flow_min_cut(net)
   baseline = base.value
   min_cut_cap = base.cut_capacity

   candidates = [i for i, e in enumerate(net.edges) if e.cap > 0]
   m = len(candidates)
   # Number of non-empty subsets of size up to budget.
   total_subsets = sum(comb(m, r) for r in range(1, min(budget, m) + 1))

   use_exhaustive = method == "exhaustive" or (
      method == "auto" and total_subsets <= exhaustive_limit
   )

   if use_exhaustive:
      best_residual = baseline
      best_combo: Tuple[int, ...] = ()
      for r in range(1, min(budget, m) + 1):
         for combo in combinations(candidates, r):
               resid = _throughput_without(net, combo)
               if resid < best_residual - 1e-9:
                  best_residual = resid
                  best_combo = combo
                  if best_residual <= 1e-9:
                     break
         if best_residual <= 1e-9:
               break
      removed = [(net.edges[i].src, net.edges[i].dst) for i in best_combo]
      return BudgetInterdiction(
         budget=budget, method="exhaustive", baseline_throughput=baseline,
         residual_throughput=best_residual, removed=removed,
         subsets_considered=total_subsets, min_cut_capacity=min_cut_cap,
      )

   # Greedy: repeatedly remove the single most damaging remaining lane.
   chosen: List[int] = []
   remaining = set(candidates)
   work = net.copy()
   for _ in range(budget):
      best_i = None
      best_resid = max_flow_min_cut(work).value
      current = best_resid
      for i in list(remaining):
         saved = work.edges[i].cap
         work.edges[i].cap = 0.0
         resid = max_flow_min_cut(work).value
         work.edges[i].cap = saved
         if resid < best_resid - 1e-9:
               best_resid = resid
               best_i = i
      if best_i is None or best_resid >= current - 1e-9:
         break  # no further improvement
      work.edges[best_i].cap = 0.0
      chosen.append(best_i)
      remaining.discard(best_i)
      if best_resid <= 1e-9:
         break
   removed = [(net.edges[i].src, net.edges[i].dst) for i in chosen]
   return BudgetInterdiction(
      budget=budget, method="greedy", baseline_throughput=baseline,
      residual_throughput=max_flow_min_cut(work).value, removed=removed,
      subsets_considered=total_subsets, min_cut_capacity=min_cut_cap,
   )
