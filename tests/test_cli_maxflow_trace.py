"""`clopt maxflow --trace`, pinned to the byte.

The trace payload grew for the teaching frontend: the data layer stopped
filtering, so it now ships the synthetic terminals, the unbounded residual
terms they carry as `None`, per-arc flows, and a step 0 before the first
augmentation. None of that belongs on a terminal, and the filtering that used
to live in `throughput` moved here, to print time.

Which makes this file the thing that says the move cost the CLI nothing. It is
a golden-output test rather than a set of shape assertions on purpose: "the
existing text output is unchanged" is a claim about the exact characters an
instructor sees, and only a literal transcript can hold it. The textbook
theater is the one pinned in full -- five nodes, three augmentations, and the
cancellation Day 2 is built around.
"""

import os

import pytest

from clopt.cli import main

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
TEXTBOOK = os.path.join(DATA, "textbook_maxflow.json")
THEATER = os.path.join(DATA, "theater_sample.json")

# The transcript as it printed before the trace payload grew, verbatim.
TEXTBOOK_TRACE = """\
Edmonds-Karp, iteration by iteration
(BFS picks a fewest-hop augmenting path each round; ties may pick a
 different-but-valid path than a handout, so this is *a* correct run.)

Iteration 1: s -> A -> B -> t
  bottleneck = min(3, 3, 5) = 3
  cumulative flow = 3
  residual (spare capacity): A->D 2  B->t 2  C->B 6  D->t 4  s->C 5
  residual (reverse/cancel): A->s 3  B->A 3  t->B 3

Iteration 2: s -> C -> B -> t
  bottleneck = min(5, 6, 2) = 2
  cumulative flow = 5
  residual (spare capacity): A->D 2  C->B 4  D->t 4  s->C 3
  residual (reverse/cancel): A->s 3  B->A 3  B->C 2  C->s 2  t->B 5

Iteration 3: s -> C -> B -> A -> D -> t
  bottleneck = min(3, 4, 3, 2, 4) = 2
  cumulative flow = 7
  * uses reverse arc(s) B->A to cancel/reroute earlier flow -- this is where \
the residual graph earns its keep
  residual (spare capacity): A->B 2  C->B 2  D->t 2  s->C 1
  residual (reverse/cancel): A->s 3  B->A 1  B->C 4  C->s 4  D->A 2  t->B 5  \
t->D 2

No augmenting path remains -> flow is maximum.

Max throughput (s->t, units/window): 7
Min-cut capacity (= max flow, by duality): 7

Witness cut -- the cheapest capacity-weighted blockade.
Sever these lanes and throughput cannot exceed the value above:
  B -> t            capacity 5
  A -> D            capacity 2

This cut is the certificate: it proves no plan can move more.
"""


def _run(capsys, *argv):
    assert main(["maxflow", *argv]) == 0
    return capsys.readouterr().out


def test_the_textbook_trace_prints_exactly_what_it_always_printed(capsys):
    assert _run(capsys, "--data", TEXTBOOK, "--trace") == TEXTBOOK_TRACE


@pytest.mark.parametrize("data", [TEXTBOOK, THEATER], ids=["textbook", "theater"])
def test_the_terminals_and_the_before_frame_stay_out_of_the_terminal(capsys, data):
    """The three filters the CLI now owns, stated as what must not appear.

    A golden transcript pins the textbook; this covers the theater too, where
    the reserved ids would otherwise turn up in twelve lanes' worth of
    residual lines.
    """
    out = _run(capsys, "--data", data, "--trace")

    assert "__source__" not in out and "__sink__" not in out
    assert "Iteration 0" not in out, "step 0 is the frontend's before-frame"
    assert "None" not in out, "an unbounded residual reached the transcript"


@pytest.mark.parametrize("data", [TEXTBOOK, THEATER], ids=["textbook", "theater"])
def test_the_printed_min_terms_match_the_printed_path(capsys, data):
    """One term per hop of the path as *printed* -- terminals filtered from both.

    The alignment the payload now guarantees survives the CLI's own filtering:
    `min(...)` still reads as one term per lane the instructor can point at.
    """
    out = _run(capsys, "--data", data, "--trace")

    lines = out.splitlines()
    iterations = [line for line in lines if line.startswith("Iteration ")]
    minima = [line for line in lines if "bottleneck = min(" in line]
    assert iterations and len(iterations) == len(minima)

    for path_line, min_line in zip(iterations, minima):
        hops = path_line.split(": ", 1)[1].count(" -> ")
        terms = min_line.split("min(", 1)[1].rsplit(")", 1)[0].count(",") + 1
        assert terms == hops, f"{path_line!r} has {hops} hops, {terms} terms"
