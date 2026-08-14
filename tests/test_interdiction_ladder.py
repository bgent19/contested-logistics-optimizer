"""The Day 4 ladder: both interdiction methods, rung by rung, with termination.

Day 4 is a walk up k. At each budget the class sees what the optimum removes
and what greedy removes, and the lesson is the *gap* between them -- so both
tracks are computed at every rung, on every dataset, including the ones where
they agree. Agreement stated is the control case; agreement absent is a blank
half-screen a student reads as "greedy wasn't run".

The three facts pinned here are the ones a renderer must not be allowed to
decide for itself:

*Termination.* The ladder stops at the first k where **both** tracks reach
zero, not where the optimum does. On the trap that is k=3, and k=3 is the
punchline: greedy spends three lanes to buy what the optimum bought with two.
Stopping at exhaustive-zero would cut the ladder off one rung before the point.

*Divergence.* `diverges` compares the removed *sets*, not the residuals. At
k=3 on the trap both tracks read zero and the sets differ by a whole lane; a
residual comparison would call that agreement and erase the lesson.

*k=1 always agrees.* Greedy's first iteration is exactly the exhaustive search
over singletons, so the first rung can never diverge. If it ever does, one of
the two searches is wrong -- not the dataset.
"""

import os

from clopt.interdiction import interdiction_ladder
from clopt.scenario import load_scenario

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
TRAP = os.path.join(DATA, "greedy_trap.json")
THEATER = os.path.join(DATA, "theater_sample.json")
TEXTBOOK = os.path.join(DATA, "textbook_maxflow.json")


def _net(path):
    return load_scenario(path).under(None)


def _removed(track):
    return set(track.removed)


# ---- the ladder's shape -----------------------------------------------------
def test_rungs_start_at_one_and_step_by_one():
    ladder = interdiction_ladder(_net(TRAP))
    assert [rung.k for rung in ladder.rungs] == [1, 2, 3]


def test_every_rung_carries_both_tracks():
    # The control case as much as the trap: a rung with one track filled in is
    # the failure this ladder exists to prevent.
    for path in (TRAP, THEATER):
        for rung in interdiction_ladder(_net(path)).rungs:
            assert rung.exhaustive.method == "exhaustive"
            assert rung.greedy.method == "greedy"
            assert rung.exhaustive.removed and rung.greedy.removed


def test_ladder_reports_the_baseline_once():
    ladder = interdiction_ladder(_net(TRAP))
    assert ladder.baseline_throughput == 140


# ---- termination ------------------------------------------------------------
def test_ladder_stops_where_both_tracks_reach_zero():
    ladder = interdiction_ladder(_net(TRAP))
    last = ladder.rungs[-1]

    assert ladder.terminated
    assert last.exhaustive.residual_throughput == 0
    assert last.greedy.residual_throughput == 0
    # Derived, not declared: the last rung is the *first* k at which both read
    # zero, so no earlier rung may have both at zero either.
    for rung in ladder.rungs[:-1]:
        assert not (
            rung.exhaustive.residual_throughput == 0
            and rung.greedy.residual_throughput == 0
        )


def test_termination_waits_for_the_worse_method():
    """The accepted cost of the rule, asserted so it is not tidied away.

    Exhaustive reaches zero at k=2 on the trap. The ladder runs to k=3 anyway,
    because greedy has not. That extra rung is Day 4's punchline, not slack.
    """
    ladder = interdiction_ladder(_net(TRAP))
    by_k = {rung.k: rung for rung in ladder.rungs}

    assert by_k[2].exhaustive.residual_throughput == 0
    assert by_k[2].greedy.residual_throughput > 0
    assert by_k[3].greedy.residual_throughput == 0
    assert len(by_k[3].greedy.removed) == 3
    assert len(by_k[3].exhaustive.removed) == 2


def test_the_agreeing_dataset_terminates_too():
    # The theater is source-limited: its three hub out-lanes are the unique
    # minimum-cardinality cut and the damage is additive, so interdiction
    # degenerates to sorting three numbers and greedy is optimal throughout.
    # The ladder must still end on a real zero rather than run to the ceiling.
    ladder = interdiction_ladder(_net(THEATER))

    assert ladder.terminated
    assert ladder.rungs[-1].exhaustive.residual_throughput == 0
    assert ladder.rungs[-1].greedy.residual_throughput == 0


def test_the_budget_ceiling_is_a_guard_not_the_rule():
    """A ceiling below the data's answer truncates and says so."""
    ladder = interdiction_ladder(_net(TRAP), max_budget=1)

    assert not ladder.terminated
    assert [rung.k for rung in ladder.rungs] == [1]


# ---- divergence -------------------------------------------------------------
def test_k_one_never_diverges():
    # Greedy's first iteration *is* the exhaustive search over singletons, so
    # this holds by construction on every dataset, trap included.
    for path in (TRAP, THEATER):
        first = interdiction_ladder(_net(path)).rungs[0]
        assert first.k == 1
        assert not first.diverges
        assert _removed(first.exhaustive) == _removed(first.greedy)


def test_the_trap_diverges_from_k_two_on():
    ladder = interdiction_ladder(_net(TRAP))
    assert [rung.diverges for rung in ladder.rungs] == [False, True, True]


def test_divergence_is_the_removed_set_not_the_residual():
    """k=3 on the trap: both tracks read zero, and it is still a divergence.

    This is the rung the whole ladder is built for -- same number, different
    price -- and a residual comparison would report it as agreement.
    """
    by_k = {rung.k: rung for rung in interdiction_ladder(_net(TRAP)).rungs}
    rung = by_k[3]

    assert rung.exhaustive.residual_throughput == rung.greedy.residual_throughput
    assert _removed(rung.exhaustive) != _removed(rung.greedy)
    assert rung.diverges


def test_the_agreeing_dataset_states_its_agreement():
    # `140 / 140`, not one number and a blank: every rung of the theater has
    # both tracks and says outright that they match.
    for rung in interdiction_ladder(_net(THEATER)).rungs:
        assert not rung.diverges
        assert _removed(rung.exhaustive) == _removed(rung.greedy)
        assert rung.exhaustive.residual_throughput == rung.greedy.residual_throughput


# ---- the identical-rung collapse --------------------------------------------
def test_no_blockade_is_ever_drawn_under_two_values_of_k():
    """The collapse rule as the property it exists to give: rungs are distinct.

    A rung is a picture, and the same picture under two labels is a slide the
    class reads as progress that did not happen. On a live network the guard
    is quiet -- while throughput is positive each extra unit of budget strictly
    improves both tracks -- so what is asserted here is the invariant, not the
    branch. It is the invariant that must survive a change to the ceiling or to
    the stop rule.
    """
    for path in (TRAP, THEATER):
        rungs = interdiction_ladder(_net(path)).rungs
        pictures = [
            (frozenset(r.exhaustive.removed), frozenset(r.greedy.removed))
            for r in rungs
        ]
        assert len(set(pictures)) == len(pictures)


def test_no_shipped_ladder_actually_collapses_a_rung():
    """`k_through == k` everywhere, which is the collapse guard reporting idle.

    Asserted rather than assumed: it is the evidence for the claim in
    `interdiction_ladder` that the guard is quiet on a live network, and it is
    what would fail first if a change to the stop rule started producing
    repeated pictures for the guard to swallow.
    """
    for path in (TRAP, THEATER, TEXTBOOK):
        for rung in interdiction_ladder(_net(path)).rungs:
            assert rung.k_through == rung.k


def test_the_collapse_test_is_the_removed_set_not_the_residual():
    """Two blockades reaching the same number by different lanes stay two rungs.

    On the trap, exhaustive reads 0 at both k=2 and k=3 and greedy reads 0 at
    k=3 -- so a residual-keyed collapse would fold rungs the removed sets say
    are different pictures. All three rungs survive.
    """
    rungs = interdiction_ladder(_net(TRAP)).rungs
    by_k = {rung.k: rung for rung in rungs}

    assert by_k[2].exhaustive.residual_throughput == 0
    assert by_k[3].exhaustive.residual_throughput == 0
    assert _removed(by_k[2].exhaustive) != _removed(by_k[3].greedy)
    assert len(rungs) == 3


# ---- searched and skipped ---------------------------------------------------
def test_greedy_reports_the_work_greedy_did_not_the_space():
    """Greedy's count is its own, and it is well short of the whole space.

    Reporting the exhaustive subset count on a greedy result is a false claim
    about work greedy never did. What is asserted is that greedy's count is its
    own and that it leaves most of the space untouched -- *not* that greedy
    always searches less than the optimum, which is untrue: the optimum stops
    the moment it severs the network, and on `textbook_maxflow` at k=2 it
    finishes in 9 evaluations to greedy's 13.
    """
    rung = {r.k: r for r in interdiction_ladder(_net(TRAP)).rungs}[3]

    assert rung.greedy.searched < rung.subsets_total
    assert rung.greedy.skipped > 0
    assert rung.greedy.searched != rung.exhaustive.searched


def test_the_counts_do_not_rank_the_two_methods():
    """The inversion, pinned, so it is not later mistaken for a regression.

    An early-breaking optimum can outrun greedy on a small instance. The counts
    describe work done; the Day 4 number is how fast `subsets_total` grows.
    """
    by_k = {r.k: r for r in interdiction_ladder(_net(TEXTBOOK)).rungs}

    assert by_k[2].exhaustive.searched == 9
    assert by_k[2].greedy.searched == 13


def test_searched_and_skipped_account_for_the_whole_space():
    for rung in interdiction_ladder(_net(TRAP)).rungs:
        for track in (rung.exhaustive, rung.greedy):
            assert track.searched >= 0 and track.skipped >= 0
            # Both tracks are measured against the same denominator: the
            # subsets an optimal search of this budget would have to consider.
            assert track.searched + track.skipped == rung.subsets_total


def test_exhaustive_skips_what_an_early_zero_saves_it():
    # The optimum stops the moment it severs the network, so even the
    # exhaustive track does not always walk the whole space.
    rung = {r.k: r for r in interdiction_ladder(_net(TRAP)).rungs}[3]
    assert rung.exhaustive.skipped > 0
