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

import json
import os

import pytest

from clopt.model import Network, Node, NodeKind
from clopt.scenario import load_scenario, network_to_dict, save_scenario

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
DATASETS = sorted(f for f in os.listdir(DATA) if f.endswith(".json"))


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


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
def test_authored_coordinates_survive_a_round_trip(filename, tmp_path):
    """A load -> save -> load cycle must not quietly drop authored positions.

    The theater's coordinates are the output of a long layout search that
    nobody is going to redo by eye, and a serialiser that forgets to write
    them back raises nothing -- the file just comes out flat. So assert the
    cycle rather than the reader alone.
    """
    source = os.path.join(DATA, filename)
    on_disk = json.loads(_read(source))
    before = {n["id"]: (n.get("x"), n.get("y")) for n in on_disk["network"]["nodes"]}
    authored = {
        node_id: position
        for node_id, position in before.items()
        if position != (None, None)
    }
    if not authored:
        # Loudly, not vacuously: an un-authored dataset has nothing to
        # preserve, and a silent pass here would look like verification.
        pytest.skip(f"{filename}: no node carries a coordinate to round-trip")

    out = tmp_path / filename
    save_scenario(load_scenario(source), str(out))
    reloaded = load_scenario(str(out))

    for node_id, position in authored.items():
        node = reloaded.network.nodes[node_id]
        assert (node.x, node.y) == position, (
            f"{filename}: node {node_id} moved {position} -> {(node.x, node.y)} "
            f"across a save/load cycle"
        )

    # Untouched means untouched, on disk as well as in memory: no scaling, no
    # flipping, and no int -> float drift that would rewrite every coordinate.
    # Unauthored nodes are covered too -- they must come back out as null.
    written = json.loads(_read(str(out)))
    for node in written["network"]["nodes"]:
        assert (node["x"], node["y"]) == before[node["id"]], (
            f"{filename}: node {node['id']} coordinates were transformed on write"
        )


@pytest.mark.parametrize("half", [{"x": 10.0}, {"y": 10.0}], ids=["x_only", "y_only"])
def test_half_a_coordinate_is_refused(half):
    # Half a coordinate is worse than none: a layout can neither place the
    # node nor tell that it is supposed to. Refused beside the other field
    # invariants, so the registry's eager scan catches a half-authored file
    # at startup and names it.
    with pytest.raises(ValueError, match="x and y"):
        Node(id="LOPSIDED", kind="transit", **half)


def test_unauthored_nodes_serialise_as_null():
    # Both shipped datasets are fully authored, so the round-trip test above
    # never reaches this branch. A layout needs to be able to tell "placed at
    # 0" apart from "not placed", which means the key is present and null --
    # not absent, and not defaulted to a number.
    net = Network()
    net.add_node(Node(id="UNPLACED", kind="transit"))

    node = network_to_dict(net)["nodes"][0]

    assert node["x"] is None and node["y"] is None


@pytest.mark.parametrize("filename", DATASETS)
def test_shipped_scenario_threat_pictures_apply(filename):
    # A threat picture that names a lane the network does not have is the
    # other way a shipped file breaks in front of a class.
    scenario = load_scenario(os.path.join(DATA, filename))
    for name in scenario.threat_pictures:
        net = scenario.under(name)
        assert net.nodes, f"{filename}: threat picture {name!r} emptied the network"
