"""Node-kind parsing, including the synonyms hand-authored scenarios use."""

import json
from pathlib import Path

import pytest

from clopt.model import Node, NodeKind

DATA = Path(__file__).resolve().parents[1] / "data"


def test_canonical_kinds_parse():
   assert NodeKind("supply") is NodeKind.SUPPLY
   assert NodeKind("demand") is NodeKind.DEMAND
   assert NodeKind("transit") is NodeKind.TRANSIT


@pytest.mark.parametrize(
   "spelling", ["transship", "transshipment", "transhipment", "TRANSSHIPMENT", " transit "]
)
def test_transshipment_synonyms_resolve_to_transit(spelling):
   assert NodeKind(spelling) is NodeKind.TRANSIT


def test_node_accepts_a_transshipment_string():
   node = Node("A", "transship")
   assert node.kind is NodeKind.TRANSIT


def test_unknown_kind_still_rejected():
   with pytest.raises(ValueError):
      NodeKind("depot")


def test_shipped_datasets_all_load():
   """Every scenario file that ships with the repo must parse.

   The textbook set is Day 2's worked example; it failing to load is a
   dead class, not a failing test.
   """
   for path in sorted(DATA.glob("*.json")):
      spec = json.loads(path.read_text())
      for raw in spec["network"]["nodes"]:
         node = Node(raw["id"], raw["kind"], raw.get("quantity", 0.0))
         assert node.kind in NodeKind
