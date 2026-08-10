"""Every dataset shipped in `data/` must load.

This file exists because one did not. `data/textbook_maxflow.json` -- the
six-node worked example the unit's Day 2 is built on -- spelled its junction
nodes `"transship"`, which `NodeKind` does not define, so the file raised on
load. Nothing loaded it directly, so the breakage was invisible until Day 2
needed it.

The parameterisation is over the *directory*, not a hand-written list, so a
third theater is covered the day the file lands rather than the day someone
remembers to add it here.
"""

import os

import pytest

from clopt.model import NodeKind
from clopt.scenario import load_scenario

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
DATASETS = sorted(f for f in os.listdir(DATA) if f.endswith(".json"))


def test_data_directory_is_not_empty():
    # Guards the guard: an empty glob would make every test below vacuous.
    assert DATASETS, f"no scenario files found in {DATA}"


@pytest.mark.parametrize("filename", DATASETS)
def test_shipped_scenario_loads(filename):
    scenario = load_scenario(os.path.join(DATA, filename))
    net = scenario.under(None)

    assert net.nodes, f"{filename}: scenario has no nodes"
    assert net.edges, f"{filename}: scenario has no edges"

    # `Node.__post_init__` coerces the JSON string to the enum; if a file
    # carries a spelling the model does not know, it raises there rather
    # than here. Assert the coercion actually happened.
    for node in net.nodes.values():
        assert isinstance(node.kind, NodeKind), (
            f"{filename}: node {node.id} kind did not coerce to NodeKind"
        )


@pytest.mark.parametrize("filename", DATASETS)
def test_shipped_scenario_threat_pictures_apply(filename):
    # A threat picture that names a lane the network does not have is the
    # other way a shipped file breaks in front of a class.
    scenario = load_scenario(os.path.join(DATA, filename))
    for name in scenario.threat_pictures:
        net = scenario.under(name)
        assert net.nodes, f"{filename}: threat picture {name!r} emptied the network"
