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

import itertools
import json
import os

import pytest

from clopt.model import Network, Node, NodeKind
from clopt.scenario import load_scenario, network_to_dict, save_scenario

from layout_geometry import (
    ANCHOR_CLEAR_OF_ANCHOR, ANCHOR_CLEAR_OF_CROSSING, ANCHOR_CLEAR_OF_NODE,
    LANE_CLEAR_OF_NODE, MIN_CROSSING_ANGLE, MIN_LANE_LENGTH, NODE_CLEAR_OF_NODE,
    crossings, distance, drawn_lanes, placed_nodes, point_to_segment,
    solve_anchors,
)

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
DATASETS = sorted(f for f in os.listdir(DATA) if f.endswith(".json"))


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _layout(filename):
    """A dataset's drawable layout, or a loud skip.

    Every geometry check below routes through here, so a dataset with no
    authored coordinates skips with a reason rather than passing vacuously --
    which, under this repo's `-rs`, prints in the summary instead of showing as
    a bare `s`.
    """
    payload = json.loads(_read(os.path.join(DATA, filename)))
    positions = placed_nodes(payload)
    if not positions:
        pytest.skip(f"{filename}: no node carries a coordinate, nothing to check")
    lanes = drawn_lanes(payload, positions)
    if not lanes:
        pytest.skip(f"{filename}: no lane has both endpoints placed")
    return positions, lanes


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


def test_an_unauthored_dataset_skips_rather_than_passing():
    """The loud-skip guard, exercised directly.

    Every shipped dataset is fully authored, so the skip path in `_layout` is
    never taken by the parameterised checks below -- which makes it exactly the
    kind of guard that is broken and never noticed. Asserting on the two
    readers it depends on is the closest a test can get without shipping a
    coordinate-free file purely to be skipped.
    """
    unauthored = {"network": {
        "nodes": [{"id": "A", "kind": "supply", "x": None, "y": None},
                  {"id": "B", "kind": "demand", "x": None, "y": None}],
        "edges": [{"src": "A", "dst": "B"}],
    }}

    positions = placed_nodes(unauthored)

    assert positions == {}, "an unplaced node was treated as placed"
    # And with nothing placed, no lane is drawable -- so the geometry checks
    # have nothing to assert and must say so rather than pass.
    assert drawn_lanes(unauthored, positions) == []


@pytest.mark.parametrize("filename", DATASETS)
def test_nodes_clear_each_other(filename):
    positions, _ = _layout(filename)
    for (a, b) in itertools.combinations(sorted(positions), 2):
        gap = distance(positions[a], positions[b])
        assert gap >= NODE_CLEAR_OF_NODE, (
            f"{filename}: nodes {a} and {b} are {gap:.1f} apart, "
            f"inside the {NODE_CLEAR_OF_NODE} two plates and their labels need"
        )


@pytest.mark.parametrize("filename", DATASETS)
def test_lanes_are_long_enough_to_carry_an_anchor(filename):
    positions, lanes = _layout(filename)
    for src, dst in lanes:
        length = distance(positions[src], positions[dst])
        assert length >= MIN_LANE_LENGTH, (
            f"{filename}: lane {src}->{dst} is {length:.1f} long, below the "
            f"{MIN_LANE_LENGTH} at which an anchor stops fitting on it"
        )


@pytest.mark.parametrize("filename", DATASETS)
def test_lanes_clear_the_nodes_they_pass(filename):
    """A lane drawn *through* a node is a topology lie.

    The one failure on this list that no amount of label placement can repair:
    it reads as an edge that stops at that node, and only a coordinate edit
    fixes it.
    """
    positions, lanes = _layout(filename)
    for src, dst in lanes:
        for node_id, point in sorted(positions.items()):
            if node_id in (src, dst):
                continue
            gap = point_to_segment(point, positions[src], positions[dst])
            assert gap >= LANE_CLEAR_OF_NODE, (
                f"{filename}: lane {src}->{dst} passes {gap:.1f} from node "
                f"{node_id}, inside {LANE_CLEAR_OF_NODE} -- it will read as "
                f"terminating there"
            )


@pytest.mark.parametrize("filename", DATASETS)
def test_every_lane_gets_a_clear_anchor(filename):
    """The anchor solve is feasible, and every anchor it places is clear.

    Both halves are needed. `solve_anchors` returning a point for each lane is
    the feasibility claim; re-checking the points it returned is what catches a
    solver that has drifted from the clearances it is supposed to honour.
    """
    positions, lanes = _layout(filename)
    anchors = solve_anchors(positions, lanes)

    unplaced = [lane for lane, point in anchors.items() if point is None]
    assert not unplaced, (
        f"{filename}: no clear anchor exists for {unplaced} -- these lanes "
        f"cannot carry their flow numeral anywhere along their length"
    )

    crossing_points = [c["point"] for c in crossings(positions, lanes)]
    for lane, point in anchors.items():
        for node_id, node in sorted(positions.items()):
            gap = distance(point, node)
            assert gap >= ANCHOR_CLEAR_OF_NODE, (
                f"{filename}: {lane} anchor sits {gap:.1f} from node {node_id}"
            )
        for crossing in crossing_points:
            gap = distance(point, crossing)
            assert gap >= ANCHOR_CLEAR_OF_CROSSING, (
                f"{filename}: {lane} anchor sits {gap:.1f} from a crossing, "
                f"under the casing cut for that crossing"
            )
    for (one, other) in itertools.combinations(sorted(anchors), 2):
        gap = distance(anchors[one], anchors[other])
        assert gap >= ANCHOR_CLEAR_OF_ANCHOR, (
            f"{filename}: anchors for {one} and {other} are {gap:.1f} apart; "
            f"their numerals will interleave"
        )


@pytest.mark.parametrize("filename", DATASETS)
def test_no_crossing_is_shallow(filename):
    """The angle floor, and deliberately *not* a crossing count.

    The count is a proven global floor for this layout -- nothing can improve
    it and nothing can silently break it, so asserting it would never fire. The
    angles are the opposite: the layout search optimised on count and
    displacement and never looked at angle, so the range it landed on is a
    windfall that nothing protects. A future coordinate edit can hold the count
    and still drive one crossing shallow, where two lanes merge into a visual
    vee and the casing stops reading as a break.
    """
    positions, lanes = _layout(filename)
    for crossing in crossings(positions, lanes):
        (one, other), angle = crossing["lanes"], crossing["angle"]
        assert angle >= MIN_CROSSING_ANGLE, (
            f"{filename}: lanes {one} and {other} cross at {angle:.1f} deg, "
            f"below the {MIN_CROSSING_ANGLE} deg floor"
        )


@pytest.mark.parametrize("filename", DATASETS)
def test_shipped_scenario_threat_pictures_apply(filename):
    # A threat picture that names a lane the network does not have is the
    # other way a shipped file breaks in front of a class.
    scenario = load_scenario(os.path.join(DATA, filename))
    for name in scenario.threat_pictures:
        net = scenario.under(name)
        assert net.nodes, f"{filename}: threat picture {name!r} emptied the network"
