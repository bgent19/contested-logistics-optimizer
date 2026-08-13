"""`Scenario.edge_changes`: what a threat picture did, per stored edge.

The API ships this so the frontend never reimplements disruption arithmetic in
JavaScript. That makes it worth testing against all five disruption kinds --
the shipped theater only exercises three, and the two it skips (`set_risk` and
the clamp on `scale_risk`) are exactly where a hand-rolled reimplementation
would be most likely to disagree.

Changes are keyed by *index*, not by `src`/`dst`, because the model permits
parallel edges. The last test here is the one that would catch a regression to
a pair-keyed lookup.
"""

import pytest

from clopt.model import Disruption, Edge, Network, Node, Scenario


def _scenario(edges, pictures):
    net = Network()
    for node_id in ("S", "M", "D"):
        kind = {"S": "supply", "M": "transit", "D": "demand"}[node_id]
        quantity = 10.0 if kind != "transit" else 0.0
        net.add_node(Node(id=node_id, kind=kind, quantity=quantity))
    for edge in edges:
        net.add_edge(edge)
    return Scenario(name="sand table", network=net, threat_pictures=pictures)


def _lane(src="S", dst="M", cap=10.0, cost=1.0, risk=0.2, **kw):
    return Edge(src=src, dst=dst, cap=cap, cost=cost, risk=risk, **kw)


def test_remove_edge_reports_zero_capacity_and_the_untouched_risk():
    sc = _scenario(
        [_lane(risk=0.2)],
        {"cut": [Disruption(kind="remove_edge", src="S", dst="M")]},
    )

    [change] = sc.edge_changes("cut")

    # Both values ride along even though only capacity moved: a lane that has
    # lost its capacity still has a risk worth drawing.
    assert (change.index, change.cap, change.risk) == (0, 0.0, 0.2)


def test_remove_node_reports_every_incident_edge():
    # The semantics most likely to be got wrong by a reimplementation: one
    # declaration naming a node, several edges changed, and the edges named
    # nowhere in the declaration.
    sc = _scenario(
        [_lane("S", "M"), _lane("M", "D"), _lane("S", "D")],
        {"struck": [Disruption(kind="remove_node", node="M")]},
    )

    changed = {c.index: c.cap for c in sc.edge_changes("struck")}

    assert changed == {0: 0.0, 1: 0.0}


def test_scale_capacity_reports_the_product():
    sc = _scenario(
        [_lane(cap=90.0)],
        {"pressure": [Disruption(kind="scale_capacity", src="S", dst="M", factor=0.4)]},
    )

    assert sc.edge_changes("pressure")[0].cap == pytest.approx(36.0)


def test_set_risk_reports_the_value():
    sc = _scenario(
        [_lane(risk=0.2)],
        {"watched": [Disruption(kind="set_risk", src="S", dst="M", value=0.7)]},
    )

    assert sc.edge_changes("watched")[0].risk == pytest.approx(0.7)


@pytest.mark.parametrize(
    "kind,field,value",
    [("set_risk", "value", 2.5), ("scale_risk", "factor", 10.0)],
    ids=["set_risk", "scale_risk"],
)
def test_risk_is_clamped_to_one(kind, field, value):
    # Risk is a weight in [0, 1]. An unclamped reimplementation would hand the
    # projector a lane 250% contested.
    sc = _scenario(
        [_lane(risk=0.5)],
        {"overrun": [Disruption(kind=kind, src="S", dst="M", **{field: value})]},
    )

    assert sc.edge_changes("overrun")[0].risk == 1.0


def test_a_declaration_that_matches_nothing_changes_nothing():
    # Disruptions match on the stored direction only, so a picture authored
    # with src/dst reversed matches no edge and fails silently. That is a
    # known cost of authoring a new theater -- pinned here so it stays known.
    sc = _scenario(
        [_lane("S", "M")],
        {"backwards": [Disruption(kind="remove_edge", src="M", dst="S")]},
    )

    assert sc.edge_changes("backwards") == []


def test_an_unchanged_edge_is_absent_rather_than_reported_as_itself():
    sc = _scenario(
        [_lane("S", "M"), _lane("M", "D")],
        {"cut": [Disruption(kind="remove_edge", src="M", dst="D")]},
    )

    assert [c.index for c in sc.edge_changes("cut")] == [1]


def test_parallel_edges_are_told_apart_by_index():
    # Two lanes between the same pair, which a "src>dst" key could not
    # distinguish. `remove_edge` zeroes both; the report must name both, with
    # each carrying its own risk rather than the first one's.
    sc = _scenario(
        [_lane("S", "M", cap=10.0, risk=0.2), _lane("S", "M", cap=40.0, risk=0.6)],
        {"cut": [Disruption(kind="remove_edge", src="S", dst="M")]},
    )

    changes = sc.edge_changes("cut")

    assert [(c.index, c.cap, c.risk) for c in changes] == [
        (0, 0.0, 0.2),
        (1, 0.0, 0.6),
    ]


def test_the_pristine_network_is_not_mutated_by_asking():
    sc = _scenario(
        [_lane(cap=10.0)],
        {"cut": [Disruption(kind="remove_edge", src="S", dst="M")]},
    )

    sc.edge_changes("cut")
    sc.edge_changes("cut")

    # Twice, because a mutating implementation would report nothing the second
    # time -- the diff against an already-disrupted "pristine" is empty.
    assert sc.network.edges[0].cap == 10.0
    assert len(sc.edge_changes("cut")) == 1


def test_an_unknown_threat_picture_raises():
    sc = _scenario([_lane()], {})
    with pytest.raises(KeyError):
        sc.edge_changes("no_such_picture")
