"""Tests for Edmonds-Karp max-flow, the min-cut certificate, and interdiction.

The max-flow tests are pinned to the unit's Day 2 worked example (max flow 14)
and Day 3 result (min cut also 14), so a regression is a concrete wrong number
against the published notes.
"""

import os

from clopt.maxflow import EdmondsKarp
from clopt.scenario import load_scenario
from clopt.throughput import max_flow_min_cut
from clopt.interdiction import budget_interdiction, min_cut_interdiction

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
TEXTBOOK = os.path.abspath(os.path.join(DATA, "textbook_maxflow.json"))
THEATER = os.path.abspath(os.path.join(DATA, "theater_sample.json"))


# ---- core Edmonds-Karp ---------------------------------------------------
def test_edmonds_karp_textbook_value():
    # Build the Day 2 graph directly: s=0,A=1,B=2,C=3,D=4,t=5
    g = EdmondsKarp(6)
    g.add_edge(0, 1, 10)  # s->A
    g.add_edge(0, 2, 10)  # s->B
    g.add_edge(1, 3, 4)   # A->C
    g.add_edge(1, 4, 2)   # A->D
    g.add_edge(2, 4, 9)   # B->D
    g.add_edge(3, 5, 10)  # C->t
    g.add_edge(4, 5, 10)  # D->t
    assert g.max_flow(0, 5) == 14


def test_max_flow_equals_min_cut_textbook():
    net = load_scenario(TEXTBOOK).under(None)
    res = max_flow_min_cut(net)
    assert res.value == 14
    # Max-Flow Min-Cut: the witness cut capacity equals the flow value.
    assert res.cut_capacity == 14
    assert len(res.cut_lanes) >= 1


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
    assert inter.cut_capacity == inter.baseline_throughput == 14


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
    assert sum(s.bottleneck for s in res.trace) == res.value == 14
    totals = [s.total_after for s in res.trace]
    assert totals == sorted(totals)
    assert totals[-1] == 14
    # Every step's path starts at the real source and ends at the real sink.
    for s in res.trace:
        assert s.path[0] == "s" and s.path[-1] == "t"
