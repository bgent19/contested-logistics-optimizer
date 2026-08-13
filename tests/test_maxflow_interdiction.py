"""Tests for Edmonds-Karp max-flow, the min-cut certificate, and interdiction.

The max-flow tests are pinned to the unit's Day 2 worked example (max flow 7)
and Day 3 result (min cut also 7), so a regression is a concrete wrong number
against the published notes.
"""

import os

from clopt.maxflow import EdmondsKarp
from clopt.scenario import load_scenario
from clopt.throughput import SUPER_SINK, SUPER_SOURCE, max_flow_min_cut
from clopt.interdiction import budget_interdiction, min_cut_interdiction

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
TEXTBOOK = os.path.abspath(os.path.join(DATA, "textbook_maxflow.json"))
THEATER = os.path.abspath(os.path.join(DATA, "theater_sample.json"))


def _augmentations(res):
    """The trace without the prepended step 0 -- one entry per augmentation.

    Named as `tests/test_api_contract.py` names its own: that one takes the
    decoded array, this one takes the result object, and they are otherwise
    the same idea on either side of the wire.
    """
    return [s for s in res.trace if s.iteration > 0]


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
    # Every augmentation runs super-source to super-sink; the terminals are
    # *retained* now (see `test_the_trace_keeps_the_synthetic_terminals`), so
    # the real source and sink sit one hop inside them.
    for s in _augmentations(res):
        assert s.path[0] == SUPER_SOURCE and s.path[1] == "s"
        assert s.path[-2] == "t" and s.path[-1] == SUPER_SINK


def test_the_trace_opens_with_a_step_zero_holding_the_initial_residual_graph():
    """Step 0 exists so the frontend has a "before" to draw iteration 1 against.

    Its uniform render rule is *residuals from step k-1, path annotation from
    step k*, and iteration 1 otherwise has no k-1. The alternative -- building
    the initial residual state in JavaScript -- puts residual-graph
    construction in the browser, which the frontend spec bans.
    """
    res = max_flow_min_cut(load_scenario(TEXTBOOK).under(None), trace=True)

    assert len(res.trace) == len(_augmentations(res)) + 1
    zero = res.trace[0]
    assert zero.iteration == 0
    assert zero.path == [] and zero.lane_residuals == []
    assert zero.bottleneck == 0 and zero.total_after == 0
    # Every lane at full capacity, nothing carrying flow yet.
    assert ("s", "A", 3.0) in zero.forward_residual
    assert zero.reverse_residual == []
    assert all(f == 0 for _, _, f in zero.flows)


def test_the_trace_keeps_the_synthetic_terminals():
    """The data layer stops filtering; the CLI filters at print time.

    Stripping the terminals made a route appear to begin mid-graph with the
    dashed arc it traverses left dark. They ship, under reserved ids that a
    scenario file's uppercase-hyphen ids cannot collide with, and their
    unbounded residual ships as `None`.
    """
    res = max_flow_min_cut(load_scenario(TEXTBOOK).under(None), trace=True)

    for step in _augmentations(res):
        assert step.path[0] == SUPER_SOURCE and step.path[-1] == SUPER_SINK
        # `None` is unbounded: the terminal arcs are built at infinity.
        assert step.lane_residuals[0] is None
        assert step.lane_residuals[-1] is None
        assert all(r is not None for r in step.lane_residuals[1:-1])


def test_lane_residuals_carry_one_term_per_arc_of_the_path():
    """The de-alignment that dropping unbounded terms used to cause.

    A `min(...)` term is only meaningful anchored to the lane it came from,
    and a filtered list cannot be indexed against the path.
    """
    for path in (TEXTBOOK, THEATER):
        res = max_flow_min_cut(load_scenario(path).under(None), trace=True)
        for step in _augmentations(res):
            assert len(step.lane_residuals) == len(step.path) - 1


def test_every_step_carries_flows_for_every_lane_including_saturated_ones():
    """A saturated lane was indistinguishable from an absent one.

    The residual lists drop an arc once it hits zero, so Day 2's most
    interesting lanes -- the saturated ones -- fell out of the payload
    entirely. `flows` covers every arc explicitly, saturated ones at their
    capacity and untouched ones at 0.
    """
    net = load_scenario(TEXTBOOK).under(None)
    res = max_flow_min_cut(net, trace=True)
    lanes = {(e.src, e.dst): e.cap for e in net.directed_edges() if e.cap > 0}

    for step in res.trace:
        flows = {(u, v): f for u, v, f in step.flows}
        assert lanes.keys() <= flows.keys()
        assert all(flows[lane] <= cap for lane, cap in lanes.items())

    final = {(u, v): f for u, v, f in res.trace[-1].flows}
    # B->t saturates at 5 and A->D at 2; both are cut lanes, and both would
    # have been missing from the residual lists at this step.
    assert final[("B", "t")] == 5
    assert final[("A", "D")] == 2


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
    steps = _augmentations(res)

    # Three augmentations, pushing 3 / 2 / 2.
    assert [s.bottleneck for s in steps] == [3, 2, 2]

    # Iteration 3 walks the backward arc B->A, cancelling 2 of the 3 units
    # committed to lane A->B in iteration 1. Partial, not total: A->B ends
    # carrying 1, so the lane visibly loses units rather than blinking out.
    assert [s.used_reverse for s in steps] == [[], [], [("B", "A")]]
    assert steps[2].path == [SUPER_SOURCE, "s", "C", "B", "A", "D", "t", SUPER_SINK]

    # Edmonds-Karp's non-decreasing path length, on screen rather than
    # asserted. Two hops longer than the hand-trace on the board: the
    # super-source and super-sink arcs are now retained.
    assert [len(s.path) - 1 for s in steps] == [5, 5, 7]
