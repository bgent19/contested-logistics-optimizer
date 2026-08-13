"""`clopt maxflow --trace` is a lecture artifact, pinned character for character.

The trace text goes on the projector beside a hand-trace on the board, so a
stray line or a reordered residual list is not a cosmetic diff -- it is the
class asking why the screen and the whiteboard disagree.

This matters most while the *data* layer is changing under it. The trace the
API ships is deliberately complete (synthetic terminals retained, unbounded
residuals carried as `None`, a step 0 prepended), and the CLI narrows that back
down at print time. These goldens were generated from the CLI as it read before
that split existed, so they are evidence the narrowing is exact rather than
approximately right.
"""

import os

import pytest

from clopt.cli import main

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
GOLDEN = os.path.join(os.path.dirname(__file__), "golden")

DATASETS = sorted(
    os.path.splitext(f)[0] for f in os.listdir(DATA) if f.endswith(".json")
)


def _run(capsys, *argv):
    assert main(list(argv)) == 0
    return capsys.readouterr().out


@pytest.mark.parametrize("stem", DATASETS)
def test_trace_output_is_byte_for_byte_the_golden(capsys, stem):
    produced = _run(capsys, "maxflow", "--data", os.path.join(DATA, f"{stem}.json"), "--trace")
    with open(os.path.join(GOLDEN, f"maxflow_trace_{stem}.txt"), encoding="utf-8") as fh:
        assert produced == fh.read()


@pytest.mark.parametrize("stem", DATASETS)
def test_the_untraced_summary_is_the_tail_of_the_traced_one(capsys, stem):
    # --trace adds a preamble and changes nothing after it, so the two runs
    # cannot drift into disagreeing about the flow value they report.
    path = os.path.join(DATA, f"{stem}.json")
    traced = _run(capsys, "maxflow", "--data", path, "--trace")
    plain = _run(capsys, "maxflow", "--data", path)
    assert traced.endswith(plain)


@pytest.mark.parametrize("stem", DATASETS)
def test_no_synthetic_terminal_reaches_the_printed_trace(capsys, stem):
    # The super-source and super-sink are the API's business. A student reading
    # the CLI should see lanes that exist in the theater and nothing else.
    produced = _run(capsys, "maxflow", "--data", os.path.join(DATA, f"{stem}.json"), "--trace")
    assert "__source__" not in produced
    assert "__sink__" not in produced


@pytest.mark.parametrize("stem", DATASETS)
def test_no_iteration_zero_and_no_unbounded_term_is_printed(capsys, stem):
    # Step 0 exists for the frontend's "residuals from k-1, path from k" render
    # rule; it is not an augmentation and the instructor never says "iteration
    # 0". `inf` reaching a min(...) line would be the unbounded terminal arcs
    # leaking out of the data layer.
    produced = _run(capsys, "maxflow", "--data", os.path.join(DATA, f"{stem}.json"), "--trace")
    assert "Iteration 0" not in produced
    assert "inf" not in produced
    assert "None" not in produced
