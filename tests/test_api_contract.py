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
