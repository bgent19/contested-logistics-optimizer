"""Tests for Edmonds-Karp max-flow, the min-cut certificate, and interdiction.

The max-flow tests are pinned to the unit's Day 2 worked example (max flow 7)
and Day 3 result (min cut also 7), so a regression is a concrete wrong number
against the published notes.
"""

import os

from conftest import edge_order

from clopt.maxflow import EdmondsKarp
from clopt.scenario import load_scenario
from clopt.throughput import max_flow_min_cut
from clopt.interdiction import budget_interdiction, min_cut_interdiction

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
TEXTBOOK = os.path.abspath(os.path.join(DATA, "textbook_maxflow.json"))
THEATER = os.path.abspath(os.path.join(DATA, "theater_sample.json"))


# ---- core Edmonds-Karp ---------------------------------------------------
def test_edmonds_karp_textbook_value():
    # Build the Day 2 graph directly: s=0,A=1,B=2,C=3,D=4,t=5.
    # Edge insertion order mirrors the JSON, which is load-bearing -- see
    # test_textbook_trace_demonstrates_cancellation.
    g = EdmondsKarp(6)
    g.add_edge(0, 1, 3)  # s->A
    g.add_edge(1, 2, 3)  # A->B
    g.add_edge(2, 5, 5)  # B->t
    g.add_edge(0, 3, 5)  # s->C
    g.add_edge(3, 2, 6)  # C->B
    g.add_edge(1, 4, 2)  # A->D
    g.add_edge(4, 5, 4)  # D->t
    assert g.max_flow(0, 5) == 7


def test_max_flow_equals_min_cut_textbook():
    net = load_scenario(TEXTBOOK).under(None)
    res = max_flow_min_cut(net)
    assert res.value == 7
    # Max-Flow Min-Cut: the witness cut capacity equals the flow value.
    assert res.cut_capacity == 7
    assert len(res.cut_lanes) >= 1
    # The cut is two *interior* lanes, not the trivial set leaving the source,
    # and the source side is the non-obvious {s, A, B, C}.
    assert {(c.src, c.dst) for c in res.cut_lanes} == {("B", "t"), ("A", "D")}
    assert set(res.source_side) == {"s", "A", "B", "C"}


# ---- theater throughput --------------------------------------------------
def test_theater_throughput_meets_demand():
    net = load_scenario(THEATER).under(None)
    res = max_flow_min_cut(net)
    # The lane network can carry at least total demand (baseline is feasible).
    assert res.value >= net.total_demand()


# ---- interdiction --------------------------------------------------------
def test_min_cut_interdiction_matches_throughput():
    net = load_scenario(TEXTBOOK).under(None)
    inter = min_cut_interdiction(net)
    # Capacity-cost to zero out flow equals the max flow (Max-Flow Min-Cut).
    assert inter.cut_capacity == inter.baseline_throughput == 7


def test_budget_interdiction_two_edges_can_sever_textbook():
    net = load_scenario(TEXTBOOK).under(None)
    res = budget_interdiction(net, budget=2, method="exhaustive")
    # Removing the right two lanes disconnects s from t entirely.
    assert res.residual_throughput == 0
    assert len(res.removed) <= 2


def test_budget_one_edge_reduces_but_may_not_sever():
    net = load_scenario(TEXTBOOK).under(None)
    res = budget_interdiction(net, budget=1, method="exhaustive")
    assert 0 <= res.residual_throughput < res.baseline_throughput


def test_greedy_is_no_better_than_exhaustive():
    """Greedy is a heuristic: it can never beat the exhaustive optimum."""
    net = load_scenario(THEATER).under(None)
    k = 2
    ex = budget_interdiction(net, budget=k, method="exhaustive")
    gr = budget_interdiction(net, budget=k, method="greedy")
    # Lower residual throughput is "better" for the interdictor.
    assert ex.residual_throughput <= gr.residual_throughput + 1e-9


def test_subset_count_reflects_combinatorics():
    """The reported search size is the C(|E|, r) sum -- the NP-hard cliff, visible."""
    net = load_scenario(THEATER).under(None)
    res = budget_interdiction(net, budget=2, method="exhaustive")
    m = len([e for e in net.network.edges if e.cap > 0]) if hasattr(net, "network") else \
        len([e for e in load_scenario(THEATER).under(None).edges if e.cap > 0])
    # 12 lanes -> C(12,1)+C(12,2) = 12 + 66 = 78 subsets.
    assert res.subsets_considered == 78


def test_trace_reaches_max_flow():
    net = load_scenario(TEXTBOOK).under(None)
    res = max_flow_min_cut(net, trace=True)
    assert res.trace, "trace should have at least one augmentation"
    # Bottlenecks sum to the max-flow value, totals are monotone, last equals value.
    assert sum(s.bottleneck for s in res.trace) == res.value == 7
    totals = [s.total_after for s in res.trace]
    assert totals == sorted(totals)
    assert totals[-1] == 7
    # Every step's path starts at the real source and ends at the real sink.
    for s in res.trace:
        assert s.path[0] == "s" and s.path[-1] == "t"


def test_textbook_trace_demonstrates_cancellation():
    """The whole reason this dataset exists: Edmonds-Karp undoes its own decision.

    The JSON edge array order is load-bearing. `throughput._build` adds lanes in
    file order and `EdmondsKarp._bfs_augmenting_path` scans `adj[u]` in insertion
    order, so the order of `edges` selects which trace the students see: of the
    5040 orderings of these 7 lanes only 25% demonstrate cancellation, and half
    collapse to a 2-iteration trace with none at all. A tidy-up that groups the
    lanes by source node would silently revert Day 2. The exact condition is
    `s->A` before `s->C` and `A->B` before `A->D`; these assertions pin it.
    """
    net = load_scenario(TEXTBOOK).under(None)
    res = max_flow_min_cut(net, trace=True)

    # Three augmentations, pushing 3 / 2 / 2.
    assert [s.bottleneck for s in res.trace] == [3, 2, 2]

    # Iteration 3 walks the backward arc B->A, cancelling 2 of the 3 units
    # committed to lane A->B in iteration 1. Partial, not total: A->B ends
    # carrying 1, so the lane visibly loses units rather than blinking out.
    assert [s.used_reverse for s in res.trace] == [[], [], [("B", "A")]]
    assert res.trace[2].path == ["s", "C", "B", "A", "D", "t"]

    # Edmonds-Karp's non-decreasing path length, on screen rather than asserted.
    assert [len(s.path) - 1 for s in res.trace] == [3, 3, 5]


def test_textbook_edge_order_is_the_cancelling_one():
    """The ordering condition itself, named, so a reordering fails by name.

    The test above already catches a reordering, but it fails as a wrong
    bottleneck list, which reads like the solver regressed rather than like
    the file was tidied. Half of the 5040 orderings collapse the trace to two
    iterations and restore exactly the bug this dataset replaced; grouping the
    lanes by source node -- the obvious tidy-up -- is one of them. This asserts
    the two precedences that select the cancelling trace.
    """
    order = edge_order(TEXTBOOK)

    assert order.index(("s", "A")) < order.index(("s", "C")), (
        "s->A must be listed before s->C, or iteration 1 takes the wrong path"
    )
    assert order.index(("A", "B")) < order.index(("A", "D")), (
        "A->B must be listed before A->D, or nothing is ever cancelled"
    )
