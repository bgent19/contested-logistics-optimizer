"""The Day 4 trap: the dataset on which greedy provably misses the optimum.

Day 4 claims that a budget interdictor who always takes the most damaging
single lane can end up strictly worse than one who searches. Every other
shipped dataset agrees with greedy, so the claim had nothing on screen behind
it. The theater cannot supply one: 0 of 240 single-capacity edits and 0 of
4,335 two-lane interior edits produce any divergence, and the coordinated
changes that did also broke Day 1. Six nodes and eight lanes is the measured
floor, so this instance is authored rather than found.

The numbers pinned below are the lesson, not implementation detail:
baseline 140, exhaustive reaching 0 at k=2, greedy stalling at 30 -- *greedy
fails when the best blockade isn't where the biggest single lane is*.
"""

import os

from conftest import edge_order

from clopt.interdiction import budget_interdiction
from clopt.scenario import load_scenario
from clopt.throughput import max_flow_min_cut

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
TRAP = os.path.join(DATA, "greedy_trap.json")


def test_trap_is_the_authored_instance():
    net = load_scenario(TRAP).under(None)
    lanes = {(e.src, e.dst): e.cap for e in net.edges}
    # Count as well as contents: the map below would swallow a duplicated
    # lane, and a ninth lane changes the instance the numbers were measured on.
    assert len(net.edges) == 8
    assert lanes == {
        ("s", "A"): 80,
        ("s", "B"): 30,
        ("s", "C"): 30,
        ("A", "D"): 80,
        ("B", "C"): 60,
        ("B", "D"): 40,
        ("C", "t"): 80,
        ("D", "t"): 80,
    }


def test_trap_nodes_use_the_abstract_register():
    # Day 2's naming, deliberately: a constructed counterexample should not
    # read as a place, or students will look for the operational reason.
    net = load_scenario(TRAP).under(None)
    assert set(net.nodes) == {"s", "A", "B", "C", "D", "t"}


def test_trap_baseline_throughput_is_140():
    net = load_scenario(TRAP).under(None)
    # 80 down s->A->D->t, 30 down s->B->C->t, 30 down s->C->t.
    assert max_flow_min_cut(net).value == 140


def test_exhaustive_severs_the_trap_with_two_lanes():
    net = load_scenario(TRAP).under(None)
    res = budget_interdiction(net, budget=2, method="exhaustive")
    assert res.residual_throughput == 0
    # C->t and D->t, the only two lanes into t. Naming them is the lesson:
    # the optimal blockade contains neither of the damage-80 lanes greedy
    # reaches for, so "biggest single lane" is not where the answer lives.
    assert set(res.removed) == {("C", "t"), ("D", "t")}


def test_one_lane_cannot_sever_the_trap():
    # "0 at k=2" only says something if k=1 falls short, otherwise greedy's
    # first pick would have been enough and there is no search to justify.
    net = load_scenario(TRAP).under(None)
    res = budget_interdiction(net, budget=1, method="exhaustive")
    assert res.residual_throughput == 60


def test_greedy_stalls_at_30_on_the_trap():
    net = load_scenario(TRAP).under(None)
    res = budget_interdiction(net, budget=2, method="greedy")
    # Greedy opens with s->A -- one of the three lanes tied at damage 80, and
    # the first of them in file order. That leaves a network whose best
    # remaining single removal is worth only 30. Pinning the opening lane
    # pins the tie-break itself, so the edge-order test below rests on
    # asserted behaviour rather than on an assumption about the solver.
    assert res.removed[0] == ("s", "A")
    assert res.residual_throughput == 30


def test_greedy_diverges_from_exhaustive_on_the_trap():
    """The Day 4 sentence, as an assertion: greedy strictly worse at equal budget."""
    net = load_scenario(TRAP).under(None)
    exhaustive = budget_interdiction(net, budget=2, method="exhaustive")
    greedy = budget_interdiction(net, budget=2, method="greedy")

    assert greedy.residual_throughput > exhaustive.residual_throughput


def test_trap_edge_order_preserves_the_divergence():
    """The JSON edge order is load-bearing, and breaks silently if reordered.

    Three lanes tie at damage 80 -- s->A, A->D and D->t -- and greedy's tie
    break is first-in-file: `throughput._build` adds lanes in file order,
    `interdiction.budget_interdiction` scans candidates in ascending index
    order, and the first strict improvement wins. Opening with s->A or A->D
    leaves a network greedy can only cut by another 30; opening with D->t
    leaves C->t as an obvious second cut and greedy reaches 0 too, erasing
    the lesson. A sweep of every ordering puts the survivors at exactly
    26,880 of 40,320 -- 66.7% -- and the condition below selects that set
    exactly. The file still loads and still draws either way, so nothing but
    this assertion would notice.
    """
    order = edge_order(TRAP)
    sink_lane_at = order.index(("D", "t"))

    assert (
        order.index(("s", "A")) < sink_lane_at or order.index(("A", "D")) < sink_lane_at
    ), "a damage-80 lane upstream of t must be listed before D->t"
