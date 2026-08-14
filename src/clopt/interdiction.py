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
   subsets_considered: int              # the whole space: C(m, <=budget), searched or not
   min_cut_capacity: float              # reference: capacity-weighted min cut

   # How the search actually spent itself. `subsets_considered` is the size of
   # the space an *optimal* search of this budget must reckon with; it is the
   # denominator, not a claim about either method's work. Reporting it as
   # greedy's own count -- which this module did until the ladder needed the
   # truth -- says greedy examined C(m, <=k) subsets, when the point of greedy
   # is that it examines a few dozen singletons and declines to look at the
   # rest. The pair below is the honest split, and it is what Day 4 puts on
   # screen: `searched` is evaluations actually performed, `skipped` is the
   # remainder of the space. Every evaluation either method makes is a distinct
   # subset of size <= budget, so the two always sum to `subsets_considered`.
   searched: int = 0
   skipped: int = 0


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
      searched = 0
      for r in range(1, min(budget, m) + 1):
         for combo in combinations(candidates, r):
               resid = _throughput_without(net, combo)
               searched += 1
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
         searched=searched, skipped=total_subsets - searched,
      )

   # Greedy: repeatedly remove the single most damaging remaining lane.
   chosen: List[int] = []
   remaining = set(candidates)
   work = net.copy()
   # Each trial below zeroes one *remaining* lane on top of the lanes already
   # chosen, so it evaluates a distinct subset of size <= budget -- which is
   # what lets `searched` be counted against the same denominator the
   # exhaustive track uses. The re-solve at the top of each iteration is the
   # already-chosen prefix, counted when it was picked, so it is not counted
   # again here.
   searched = 0
   for _ in range(budget):
      best_i = None
      best_resid = max_flow_min_cut(work).value
      current = best_resid
      # Ascending index order, i.e. the order the lanes are listed in the
      # dataset file, because the first strict improvement below wins the
      # tie. On `data/greedy_trap.json` three lanes tie at damage 80 and
      # which one greedy opens with decides whether Day 4 has a divergence
      # to point at, so this order is a promise to the datasets and not an
      # implementation detail. Iterating the set directly happens to give
      # the same order for small contiguous indices; `sorted` means it
      # still does when the candidate list is sparse.
      for i in sorted(remaining):
         saved = work.edges[i].cap
         work.edges[i].cap = 0.0
         resid = max_flow_min_cut(work).value
         searched += 1
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
      searched=searched, skipped=total_subsets - searched,
   )


# ---- the Day 4 ladder -------------------------------------------------------
# A walk up k with both methods side by side. It lives here, next to the two
# searches it drives, rather than in the API or a renderer, because everything
# it decides -- when to stop, whether two tracks agree -- is arithmetic over
# solver results, and arithmetic over solver results is testable in a way that
# a render pass is not.
#
# The alternative was for the frontend to probe both methods at every k on
# every dataset at boot and decide the ladder's length in JavaScript. That puts
# how long Day 4 runs in the browser, and turns the identical-rung rule into
# behaviour no test can reach. It also costs 2 x K x datasets requests at boot
# where this costs one per dataset.

_ZERO = 1e-9


@dataclass
class InterdictionTrack:
   """One method's answer at one budget."""

   method: str                          # "exhaustive" or "greedy"
   removed: List[Tuple[str, str]]
   residual_throughput: float
   searched: int
   skipped: int


@dataclass
class LadderRung:
   """One budget, both methods, and whether they parted ways.

   `k_through` is the largest budget this rung speaks for. It equals `k` unless
   consecutive budgets produced the identical picture and were collapsed --
   see `interdiction_ladder`.
   """

   k: int
   k_through: int
   exhaustive: InterdictionTrack
   greedy: InterdictionTrack
   # The denominator both tracks' counts are measured against: the subsets an
   # optimal search of this budget must reckon with. See `BudgetInterdiction`.
   subsets_total: int
   # Computed here, not inferred by a renderer. It compares the removed *sets*
   # and not the residuals, and the difference is the whole of Day 4: at k=3 on
   # `greedy_trap` both tracks read zero and the sets differ by a lane, which
   # is precisely the lesson -- same result, one lane more expensive. A
   # residual comparison would report that rung as agreement.
   #
   # Read the other way round, `not diverges` is the instruction to draw the
   # rung as one picture rather than two: identical removed sets are one
   # blockade, however it was arrived at.
   diverges: bool


@dataclass
class InterdictionLadder:
   baseline_throughput: float
   min_cut_capacity: float
   rungs: List[LadderRung] = field(default_factory=list)
   # True when the ladder ended because both tracks reached zero, False when
   # `max_budget` cut it short. A truncated ladder is still a usable ladder;
   # it just must not be read as "and then the network was severed".
   terminated: bool = False


def _track(res: BudgetInterdiction) -> InterdictionTrack:
   return InterdictionTrack(
      method=res.method, removed=list(res.removed),
      residual_throughput=res.residual_throughput,
      searched=res.searched, skipped=res.skipped,
   )


def _same_picture(a: LadderRung, b: LadderRung) -> bool:
   """Do two rungs remove the same lanes on both tracks?

   The test is the removed set on each track, never the residual: two
   blockades that reach the same number by different lanes are two pictures.
   """
   return (
      set(a.exhaustive.removed) == set(b.exhaustive.removed)
      and set(a.greedy.removed) == set(b.greedy.removed)
   )


def interdiction_ladder(
   net: Network,
   max_budget: int = 8,
) -> InterdictionLadder:
   """Rungs k=1..K with both methods at every rung, stopping when both hit zero.

   Both tracks are requested *explicitly*. `method="auto"` is never used: on
   any classroom-sized dataset the whole subset space fits under its limit, so
   auto silently returns the exhaustive optimum and never computes greedy at
   all -- a ladder built on it would draw the same answer in both columns and
   claim the two methods agree.

   K is the first budget at which **both** tracks reach zero throughput, not
   the first at which the optimum does. The rule is a strict generalisation:
   where the methods agree it collapses back to the single-track one. Where
   they do not -- `data/greedy_trap.json` -- exhaustive is done at k=2 and the
   ladder runs to k=3 anyway, because k=3 is where greedy finally severs the
   network and the class can see it spent three lanes to buy what the optimum
   bought with two. The cost, accepted: the ladder's length is set by the
   worse method.

   `max_budget` is a ceiling on cost, not the stopping rule -- a guard so that
   an unforeseen dataset cannot walk an exhaustive search up k indefinitely
   while a class waits. Hitting it leaves `terminated` False.
   """
   base = max_flow_min_cut(net)
   ladder = InterdictionLadder(
      baseline_throughput=base.value, min_cut_capacity=base.cut_capacity,
   )
   # Past m removals there is nothing left to remove, so the ceiling never
   # needs to exceed the number of lanes with capacity.
   ceiling = min(max_budget, max(1, sum(1 for e in net.edges if e.cap > 0)))

   for k in range(1, ceiling + 1):
      exhaustive = budget_interdiction(net, budget=k, method="exhaustive")
      greedy = budget_interdiction(net, budget=k, method="greedy")
      rung = LadderRung(
         k=k, k_through=k,
         exhaustive=_track(exhaustive), greedy=_track(greedy),
         subsets_total=exhaustive.subsets_considered,
         diverges=set(exhaustive.removed) != set(greedy.removed),
      )
      # The identical-rung collapse. While throughput is positive every extra
      # unit of budget strictly improves both tracks -- removing any lane of a
      # positive min cut lowers the cut, and both searches take the first
      # strict improvement they find -- so on a live network no two rungs can
      # repeat, and once both tracks are at zero the loop below stops. The
      # guard is therefore quiet on every dataset the unit ships. It stays
      # because "no rung is ever drawn twice" should be a property of the
      # ladder rather than a coincidence of the stop rule: a later change to
      # either -- a taller ceiling, a different termination -- must not put the
      # same blockade on the projector under two different values of k.
      if ladder.rungs and _same_picture(ladder.rungs[-1], rung):
         ladder.rungs[-1].k_through = k
      else:
         ladder.rungs.append(rung)

      if (exhaustive.residual_throughput <= _ZERO
            and greedy.residual_throughput <= _ZERO):
         ladder.terminated = True
         break

   return ladder
