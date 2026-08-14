"""Shared test helpers.

`edge_order` lives here because two datasets now pin their JSON edge order --
Day 2's cancelling trace and Day 4's greedy divergence -- and both need to read
the array as written rather than as loaded. `load_scenario` would do just as
well today, but reading the file directly keeps the assertion about the *file*,
which is the thing a tidy-up would edit.
"""

import json


def edge_order(path):
    """The lanes of a dataset in the order the JSON file lists them."""
    with open(path, "r", encoding="utf-8") as fh:
        return [(e["src"], e["dst"]) for e in json.load(fh)["network"]["edges"]]
