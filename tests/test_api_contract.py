"""The HTTP contract the teaching frontend is written against.

The API had no tests at all until this file: the whole suite exercised the
algorithmic core directly, while the one surface a browser can actually reach
went unchecked. What is pinned here is the shape of the contract -- dataset
ids, cycle order, and the promise that omitting `dataset` means the default --
not the numbers, which the core's own tests already cover.

The per-dataset cases parameterise over `GET /datasets`, so a third theater is
covered the day its file lands in `data/` rather than the day someone
remembers to add it here.
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from clopt import api
from clopt.datasets import DEFAULT_DATA_PATH, DatasetLoadError, build_registry

client = TestClient(api.app)

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
SHIPPED_STEMS = sorted(
    os.path.splitext(f)[0] for f in os.listdir(DATA) if f.endswith(".json")
)

CATALOG = client.get("/datasets").json()
DATASET_IDS = [entry["id"] for entry in CATALOG]
DEFAULT_ID = DATASET_IDS[0]


def _endpoint_cases(dataset_id):
    """Every endpoint, with arguments valid for `dataset_id`.

    Returns (label, path, params) triples. `/route` needs real node ids, so
    they are read from the dataset itself rather than hard-coded.
    """
    net = api.get_registry().scenario(dataset_id).network
    src = net.supply_nodes()[0].id
    dst = net.demand_nodes()[0].id
    return [
        ("scenario", "/scenario", {}),
        ("allocate", "/allocate", {"risk_aversion": 25}),
        ("route", "/route", {"from": src, "to": dst}),
        ("sweep", "/sweep", {"lambdas": "0,10"}),
        ("maxflow", "/maxflow", {}),
        ("interdict", "/interdict", {"budget": 1}),
    ]


DEFAULT_ENDPOINTS = [(p, q) for _, p, q in _endpoint_cases(DEFAULT_ID)]
ENDPOINT_IDS = [label for label, _, _ in _endpoint_cases(DEFAULT_ID)]


# ---- the catalog ------------------------------------------------------------
def test_datasets_covers_every_shipped_file():
    assert sorted(DATASET_IDS) == SHIPPED_STEMS


def test_dataset_ids_are_filename_stems_not_display_names():
    # The JSON `name` field is prose with spaces and parentheses; it is never
    # a key, because renaming the prose must not break a URL.
    for entry in CATALOG:
        assert entry["id"] in SHIPPED_STEMS
        assert entry["name"] != entry["id"]


def test_datasets_cycle_order_is_default_then_alphabetical():
    # The head is pinned to the *environment's* default, not to the registry
    # that produced the list -- asking the registry whether it agrees with
    # itself would pass no matter which file it picked.
    expected_default = os.path.splitext(
        os.path.basename(os.environ.get("CLOPT_DATA", DEFAULT_DATA_PATH))
    )[0]
    remainder = DATASET_IDS[1:]
    assert DATASET_IDS[0] == expected_default
    assert remainder == sorted(remainder)


def test_the_shipped_theaters_are_addressable_by_their_stems():
    # The one place literal ids are pinned: every URL in the README, the
    # Makefile, and the frontend spells these. A third theater lands without
    # touching this test.
    registry = build_registry(
        data_dir=DATA, default_path=os.path.join(DATA, "theater_sample.json")
    )
    assert registry.ids[0] == "theater_sample"
    assert "textbook_maxflow" in registry.ids[1:]


def test_datasets_entries_carry_only_id_name_description():
    # The full payload lives at /scenario. If the catalog grew a second copy
    # of it, the schema would have two homes and they would drift.
    for entry in CATALOG:
        assert set(entry) == {"id", "name", "description"}


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_catalog_name_and_description_match_the_file(dataset_id):
    with open(os.path.join(DATA, f"{dataset_id}.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    entry = next(e for e in CATALOG if e["id"] == dataset_id)
    assert entry["name"] == raw["name"]
    assert entry["description"] == raw["description"]


# ---- the dataset parameter --------------------------------------------------
@pytest.mark.parametrize("dataset_id", DATASET_IDS)
@pytest.mark.parametrize("label", ENDPOINT_IDS)
def test_every_endpoint_serves_every_dataset(dataset_id, label):
    path, params = next(
        (p, dict(q)) for lbl, p, q in _endpoint_cases(dataset_id) if lbl == label
    )
    params["dataset"] = dataset_id
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("path,params", DEFAULT_ENDPOINTS, ids=ENDPOINT_IDS)
def test_omitting_dataset_equals_naming_the_default(path, params):
    implicit = client.get(path, params=params)
    explicit = client.get(path, params={**params, "dataset": DEFAULT_ID})
    assert implicit.status_code == explicit.status_code == 200
    assert implicit.json() == explicit.json()


@pytest.mark.parametrize("path,params", DEFAULT_ENDPOINTS, ids=ENDPOINT_IDS)
def test_unknown_dataset_is_a_clean_404(path, params):
    response = client.get(path, params={**params, "dataset": "no_such_theater"})
    assert response.status_code == 404
    assert "no_such_theater" in response.json()["detail"]


def test_datasets_endpoint_serves_the_dataset_the_scenario_endpoint_does():
    for entry in CATALOG:
        summary = client.get("/scenario", params={"dataset": entry["id"]}).json()
        assert summary["name"] == entry["name"]


# ---- the /scenario payload --------------------------------------------------
# `/scenario` is the endpoint the frontend draws from, so what is pinned here
# is the drawable payload: the stored edges and nothing but the stored edges,
# ids that index into the file's own edge order, and every threat picture's
# effects already computed. The numbers are the file's; the shapes are ours.
def _raw(dataset_id):
    with open(os.path.join(DATA, f"{dataset_id}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _payload(dataset_id):
    response = client.get("/scenario", params={"dataset": dataset_id})
    assert response.status_code == 200, response.text
    return response.json()


PAYLOADS = [(i, _payload(i), _raw(i)) for i in DATASET_IDS]
PAYLOAD_CASES = pytest.mark.parametrize(
    "payload,raw", [(p, r) for _, p, r in PAYLOADS], ids=[i for i, _, _ in PAYLOADS]
)


@PAYLOAD_CASES
def test_counts_are_integers_and_the_arrays_live_under_network(payload, raw):
    # The rename that forced itself: `nodes` cannot mean both an integer and
    # an array, so the summary keys became `node_count`/`edge_count` and the
    # arrays moved inside `network`.
    assert payload["node_count"] == len(raw["network"]["nodes"])
    assert payload["edge_count"] == len(raw["network"]["edges"])
    assert isinstance(payload["network"]["nodes"], list)
    assert isinstance(payload["network"]["edges"], list)


@PAYLOAD_CASES
def test_ships_the_stored_edges_and_never_a_reverse_arc(payload, raw):
    """The single most costly thing this endpoint could get wrong.

    A bidirectional lane is one stored edge that the *solver* expands into two
    directed arcs. If the payload shipped the expansion, every such lane would
    be drawn twice, and an interdiction result naming one of the pair would
    mean "this arc" when the model's truth is "both arcs". Twelve edges on the
    theater, seven on the textbook -- the file's own count, expansion or no.
    """
    stored = [(e["src"], e["dst"]) for e in raw["network"]["edges"]]
    shipped = [(e["src"], e["dst"]) for e in payload["network"]["edges"]]

    assert shipped == stored

    # Belt and braces: the reverse of a bidirectional lane must not appear as
    # an entry of its own, which `shipped == stored` only catches while no
    # file happens to author both directions separately.
    bidirectional = [
        (e["src"], e["dst"])
        for e in raw["network"]["edges"]
        if e.get("bidirectional", False)
    ]
    for src, dst in bidirectional:
        assert (dst, src) not in shipped, (
            f"reverse arc {dst}->{src} shipped; the frontend derives reverses "
            f"and would draw this lane twice"
        )


def test_the_theater_bidirectional_lane_is_one_entry_not_two():
    # Guards the guard above: it is only meaningful while some shipped file
    # actually authors a bidirectional lane.
    theater = _raw("theater_sample")
    assert any(e.get("bidirectional") for e in theater["network"]["edges"])


@PAYLOAD_CASES
def test_edge_ids_are_contiguous_unique_and_zero_padded(payload, raw):
    # The id *is* the stored-edge index, because the model permits parallel
    # edges and a "src>dst" composite is not guaranteed unique.
    ids = [e["id"] for e in payload["network"]["edges"]]
    assert ids == [f"e{i:02d}" for i in range(len(raw["network"]["edges"]))]
    assert len(set(ids)) == len(ids)


@PAYLOAD_CASES
def test_edges_carry_the_drawable_attributes_as_floats(payload, raw):
    for shipped, stored in zip(payload["network"]["edges"], raw["network"]["edges"]):
        assert isinstance(shipped["cap"], float)
        assert isinstance(shipped["cost"], float)
        assert isinstance(shipped["risk"], float)
        assert shipped["cap"] == stored["cap"]
        assert shipped["cost"] == stored["cost"]
        assert shipped["risk"] == stored.get("risk", 0.0)
        assert shipped["bidirectional"] == stored.get("bidirectional", False)


@PAYLOAD_CASES
def test_nodes_carry_id_kind_quantity_and_label(payload, raw):
    shipped = {n["id"]: n for n in payload["network"]["nodes"]}
    assert set(shipped) == {n["id"] for n in raw["network"]["nodes"]}
    for stored in raw["network"]["nodes"]:
        node = shipped[stored["id"]]
        assert node["kind"] == stored["kind"]
        assert node["quantity"] == float(stored.get("quantity", 0.0))
        assert isinstance(node["quantity"], float)
        assert node["label"] == stored.get("label", "")


@PAYLOAD_CASES
def test_node_coordinates_are_both_or_neither(payload, raw):
    for node in payload["network"]["nodes"]:
        assert (node["x"] is None) == (node["y"] is None), (
            f"node {node['id']} carries half a coordinate; a layout cannot "
            f"place it and cannot tell that it should place it"
        )


def test_a_half_authored_coordinate_stops_the_server_at_startup(tmp_path):
    """Both shipped files are fully authored, so the assertion above never
    reaches this branch -- it would pass on a server that did not check.

    The refusal belongs at load time, not response time: an instructor
    authoring a fourth theater should be told by a server that will not start
    and names the file, rather than by a 500 on the first request in front of
    a class. That is the same bargain the registry already strikes.
    """
    scenario = _minimal_scenario()
    scenario["network"]["nodes"][0]["x"] = 10  # ... and no y.
    path = tmp_path / "lopsided.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")

    with pytest.raises(DatasetLoadError) as exc:
        build_registry(data_dir=str(tmp_path), default_path=str(path))

    assert "lopsided.json" in str(exc.value)
    assert "x and y" in str(exc.value)


@PAYLOAD_CASES
def test_authored_coordinates_reach_the_payload_untransformed(payload, raw):
    authored = {
        n["id"]: (n["x"], n["y"])
        for n in raw["network"]["nodes"]
        if n.get("x") is not None
    }
    if not authored:
        pytest.skip("no node in this dataset carries an authored coordinate")
    shipped = {n["id"]: (n["x"], n["y"]) for n in payload["network"]["nodes"]}
    for node_id, position in authored.items():
        assert shipped[node_id] == position


def test_the_theater_chokepoint_sits_where_the_layout_search_put_it():
    # STRAIT-3 at x=300 is the whole point of the layout work in #30: the
    # chokepoint stays on ALPHA's side so the bypass reads as a bypass.
    nodes = {n["id"]: n for n in _payload("theater_sample")["network"]["nodes"]}
    assert (nodes["STRAIT-3"]["x"], nodes["STRAIT-3"]["y"]) == (300.0, 400.0)


@PAYLOAD_CASES
def test_every_threat_picture_carries_disruptions_and_changes(payload, raw):
    # Holds vacuously on the textbook set, which declares no threat pictures.
    assert set(payload["threat_pictures"]) == set(raw["threat_pictures"])
    for name, picture in payload["threat_pictures"].items():
        assert isinstance(picture["disruptions"], list)
        assert isinstance(picture["changes"], list)
        assert picture["disruptions"], f"{name}: declared with no disruptions"


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_changes_agree_with_applying_the_disruptions_in_the_core(dataset_id):
    """The *wiring* from `Scenario.under` out to the payload -- not the arithmetic.

    This mirrors `Scenario.edge_changes`, so it cannot tell you the diffing
    is correct; what it pins is that every changed edge reaches the payload,
    under the right threat picture's key, with the right `e00` id. The
    arithmetic is checked where it cannot be circular: literally, against
    hand-worked numbers in the test below, and per disruption kind in
    `tests/test_threat_changes.py`.
    """
    payload = _payload(dataset_id)
    scenario = api.get_registry().scenario(dataset_id)
    pristine = scenario.network
    for name, picture in payload["threat_pictures"].items():
        disrupted = scenario.under(name)
        expected = {
            f"e{i:02d}": (after.cap, after.risk)
            for i, (before, after) in enumerate(zip(pristine.edges, disrupted.edges))
            if (before.cap, before.risk) != (after.cap, after.risk)
        }
        actual = {c["id"]: (c["cap"], c["risk"]) for c in picture["changes"]}
        assert actual == expected, f"{name}: changes disagree with Scenario.under"


def test_the_theaters_changes_are_the_five_hand_checked_edges():
    """Pinned literally, so the test cannot drift along with the code.

    Recomputing from the core proves agreement; it does not prove the
    arithmetic is right. These five are worked by hand off the file: two lanes
    zeroed by the mining, BRAVO's one incident lane zeroed by the strike, and
    the pressure picture's 90 -> 36 capacity and 0.30 -> 0.45 risk.
    """
    pictures = _payload("theater_sample")["threat_pictures"]
    changes = {
        name: {c["id"]: (c["cap"], c["risk"]) for c in p["changes"]}
        for name, p in pictures.items()
    }

    assert changes["strait_mined"] == {"e01": (0.0, 0.45), "e06": (0.0, 0.40)}
    assert changes["bravo_struck"] == {"e02": (0.0, 0.15)}
    # `approx` on the scaled risk, not on the code: 0.30 * 1.5 really is
    # 0.44999999999999996 in binary floating point, and the payload ships what
    # the arithmetic produced rather than a rounded-off version of it. A
    # projector caption is the frontend's place to format.
    assert changes["j2_pressure"]["e03"] == (36.0, 0.10)
    assert changes["j2_pressure"]["e09"] == pytest.approx((30.0, 0.45))
    assert sum(len(c) for c in changes.values()) == 5


def test_instructor_narration_survives_into_the_payload():
    # `note` is instructor-written prose that nothing in the repo has ever
    # rendered. On a projector it is the caption.
    pictures = _payload("theater_sample")["threat_pictures"]
    notes = [d["note"] for p in pictures.values() for d in p["disruptions"]]

    assert all(notes), "a disruption reached the payload with its note stripped"
    assert any("mined" in n for n in notes)

    authored = {
        d.get("note", "")
        for ds in _raw("theater_sample")["threat_pictures"].values()
        for d in ds
    }
    assert set(notes) == authored


def test_disruption_declarations_keep_the_fields_that_identify_their_target():
    pictures = _payload("theater_sample")["threat_pictures"]
    by_kind = {
        d["kind"]: d for p in pictures.values() for d in p["disruptions"]
    }

    assert by_kind["remove_edge"]["src"] and by_kind["remove_edge"]["dst"]
    assert by_kind["remove_node"]["node"] == "HUB-BRAVO"
    assert by_kind["scale_capacity"]["factor"] == 0.4


@PAYLOAD_CASES
def test_summary_fields_stay_a_strict_subset_of_the_grown_payload(payload, raw):
    assert payload["name"] == raw["name"]
    assert payload["description"] == raw["description"]
    assert isinstance(payload["total_supply"], float)
    assert isinstance(payload["total_demand"], float)


def test_scenario_accepts_no_threat_parameter():
    # The pristine network is returned always. Threat *effects* ship inside
    # the payload, so a `threat` param would be a second way to say the same
    # thing -- and the one the frontend would accidentally depend on.
    params = client.app.openapi()["paths"]["/scenario"]["get"].get("parameters", [])
    assert [p["name"] for p in params] == ["dataset"]


def test_passing_a_threat_anyway_still_returns_the_pristine_network():
    pristine = _payload("theater_sample")
    with_threat = client.get(
        "/scenario", params={"dataset": "theater_sample", "threat": "strait_mined"}
    )
    assert with_threat.status_code == 200
    assert with_threat.json() == pristine


def test_the_payload_is_a_documented_schema_not_a_bare_dict():
    # Unlike the result endpoints, this is a contract, and /docs should say so.
    schema = client.app.openapi()["paths"]["/scenario"]["get"]["responses"]["200"]
    ref = schema["content"]["application/json"]["schema"]["$ref"]
    name = ref.rsplit("/", 1)[-1]
    properties = client.app.openapi()["components"]["schemas"][name]["properties"]
    assert {"node_count", "edge_count", "network", "threat_pictures"} <= set(properties)


# ---- the sweep carries the plans it describes -------------------------------
# Day 1's A/B flip needs the *optimum* in hand at every lambda before the first
# keypress, and the frontend renders synchronously -- a keypress can never await
# a fetch. So the sweep stopped being a scalar summary and became everything
# about the optimum at each lambda.
LEG_FIELDS = {"src", "dst", "flow", "cost", "risk"}

SWEEP_LAMBDAS = [0.0, 10.0, 25.0]
SWEEP_QUERY = ",".join(str(lam) for lam in SWEEP_LAMBDAS)


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_sweep_returns_one_row_per_requested_lambda(dataset_id):
    rows = client.get(
        "/sweep", params={"lambdas": SWEEP_QUERY, "dataset": dataset_id}
    ).json()
    assert [row["risk_aversion"] for row in rows] == SWEEP_LAMBDAS


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_every_sweep_row_carries_the_legs_of_its_plan(dataset_id):
    rows = client.get(
        "/sweep", params={"lambdas": SWEEP_QUERY, "dataset": dataset_id}
    ).json()
    for row in rows:
        assert "legs" in row, row
        # Non-emptiness is tied to the row delivering something, not asserted
        # flat: a fully interdicted theater optimally moves nothing, and that
        # is a correct empty plan, not a missing one.
        if row["fill_rate"] > 0:
            assert row["legs"], f"lambda {row['risk_aversion']} delivered with no legs"
        for leg in row["legs"]:
            assert set(leg) == LEG_FIELDS


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_sweep_legs_are_the_same_plan_allocate_serves_at_that_lambda(dataset_id):
    # The whole point of folding legs in: the prefetched row and the one-lambda
    # call must be the same plan, or the flip would show the class something
    # /allocate disagrees with.
    rows = client.get(
        "/sweep", params={"lambdas": SWEEP_QUERY, "dataset": dataset_id}
    ).json()
    for row in rows:
        allocation = client.get(
            "/allocate",
            params={"risk_aversion": row["risk_aversion"], "dataset": dataset_id},
        ).json()
        assert row["legs"] == allocation["legs"]


def test_allocate_response_shape_is_untouched():
    # The sweep grew; /allocate did not. Pinned because the frontend's A side
    # and B side are read from the two endpoints interchangeably.
    body = client.get("/allocate", params={"risk_aversion": 10}).json()
    assert set(body) == {
        "risk_aversion", "delivered", "total_demand", "fill_rate",
        "transit_cost", "risk_exposure", "blended_cost", "legs",
    }
    for leg in body["legs"]:
        assert set(leg) == LEG_FIELDS


# ---- the registry itself ----------------------------------------------------
def test_registry_scans_the_data_directory_eagerly(tmp_path):
    # Every file is in memory before anything asks for it. Deleting the file
    # after the scan and still being served proves the scan was not lazy --
    # and laziness is what let a broken dataset hide until Day 2.
    path = tmp_path / "sandtable.json"
    path.write_text(json.dumps(_minimal_scenario()), encoding="utf-8")
    registry = build_registry(data_dir=str(tmp_path), default_path=str(path))

    os.remove(path)

    assert registry.scenario("sandtable").network.nodes


def test_a_file_that_will_not_load_fails_loudly_by_name(tmp_path):
    good = tmp_path / "good_theater.json"
    good.write_text(json.dumps(_minimal_scenario()), encoding="utf-8")
    bad = tmp_path / "broken_theater.json"
    bad.write_text("{ not json", encoding="utf-8")

    with pytest.raises(DatasetLoadError) as exc:
        build_registry(data_dir=str(tmp_path), default_path=str(good))
    assert "broken_theater.json" in str(exc.value)


def test_a_missing_data_directory_names_the_directory_it_looked_for(tmp_path):
    # The likeliest startup failure of all: the server launched from the
    # wrong working directory. `os.listdir` alone would name nothing.
    missing = str(tmp_path / "not_the_repo_root" / "data")
    with pytest.raises(DatasetLoadError) as exc:
        build_registry(data_dir=missing)
    assert missing in str(exc.value)


def test_two_files_claiming_one_stem_refuse_to_start(tmp_path):
    # A CLOPT_DATA path outside data/ joins under its own stem -- unless that
    # stem is already taken, in which case the id would be ambiguous.
    collision = tmp_path / "theater_sample.json"
    collision.write_text(json.dumps(_minimal_scenario()), encoding="utf-8")
    with pytest.raises(DatasetLoadError) as exc:
        build_registry(data_dir=DATA, default_path=str(collision))
    assert "theater_sample" in str(exc.value)


def test_data_path_outside_the_data_directory_joins_under_its_own_stem(tmp_path):
    outside = tmp_path / "sandtable.json"
    outside.write_text(json.dumps(_minimal_scenario()), encoding="utf-8")

    registry = build_registry(data_dir=DATA, default_path=str(outside))

    assert registry.default_id == "sandtable"
    assert registry.ids == ["sandtable"] + SHIPPED_STEMS
    assert registry.scenario(None) is registry.scenario("sandtable")


def test_unknown_id_raises_keyerror_naming_the_known_ids():
    registry = build_registry(data_dir=DATA)
    with pytest.raises(KeyError) as exc:
        registry.scenario("no_such_theater")
    assert "no_such_theater" in str(exc.value)


def test_serving_a_registry_whose_default_lives_outside_data(tmp_path):
    # The CLOPT_DATA-points-elsewhere case, end to end: a one-off theater is
    # addressable like any other, and it heads the cycle.
    outside = tmp_path / "sandtable.json"
    outside.write_text(json.dumps(_minimal_scenario()), encoding="utf-8")
    previous = api.use_registry(build_registry(data_dir=DATA, default_path=str(outside)))
    try:
        catalog = client.get("/datasets").json()
        assert [e["id"] for e in catalog] == ["sandtable"] + SHIPPED_STEMS
        assert client.get("/scenario").json() == client.get(
            "/scenario", params={"dataset": "sandtable"}
        ).json()
    finally:
        api.use_registry(previous)


def _minimal_scenario():
    return {
        "name": "Sand table",
        "description": "A two-node theater used only by the tests.",
        "network": {
            "nodes": [
                {"id": "S", "kind": "supply", "quantity": 5},
                {"id": "D", "kind": "demand", "quantity": 5},
            ],
            "edges": [{"src": "S", "dst": "D", "cap": 5, "cost": 1, "risk": 0.1}],
        },
        "threat_pictures": {},
    }
