"""The dataset registry: every theater in `data/` addressable by name.

One running server serves every dataset, so switching from the textbook
network to the theater mid-class is a query parameter rather than a restart.

Two decisions are load-bearing:

*Eager.* The whole directory is scanned and loaded at startup. A file that
will not load takes the process down at start, naming itself, instead of
waiting to become a 500 in front of a class. That failure has happened once
already -- `data/textbook_maxflow.json` spelled a node kind the model does not
define -- and laziness is what let it hide.

*Stems are ids.* `theater_sample`, `textbook_maxflow`. The JSON `name` field is
display prose for a menu; it is never a key, because renaming the prose must
not break a URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .model import Scenario
from .scenario import load_scenario

DATA_DIR = "data"
DEFAULT_DATA_PATH = os.path.join(DATA_DIR, "theater_sample.json")


class DatasetLoadError(RuntimeError):
   """A file the registry must serve would not load. Always names the file."""


@dataclass(frozen=True)
class Dataset:
   """One loaded scenario, plus the id and path it was found under."""

   id: str
   path: str
   scenario: Scenario

   def summary(self) -> Dict[str, str]:
      """The catalog row: enough to draw a menu, and nothing more.

      Deliberately not the full payload -- that lives at `/scenario`, and a
      schema with two homes drifts.
      """
      return {
         "id": self.id,
         "name": self.scenario.name,
         "description": self.scenario.description,
      }


class DatasetRegistry:
   """Loaded datasets, keyed by stem, in cycle order.

   Cycle order is the default first, then the remainder alphabetical. That way
   the opening screen and index 0 agree, and stepping forward always moves
   *away* from home. Plain alphabetical was rejected: renaming a file would
   silently reorder the cycle out from under the class.
   """

   def __init__(self, datasets: Sequence[Dataset], default_id: str) -> None:
      by_id: Dict[str, Dataset] = {}
      for ds in datasets:
         if ds.id in by_id:
            raise DatasetLoadError(
               f"Duplicate dataset id '{ds.id}': {by_id[ds.id].path} and {ds.path}."
            )
         by_id[ds.id] = ds
      if default_id not in by_id:
         raise DatasetLoadError(f"Default dataset '{default_id}' is not in the registry.")
      self._by_id = by_id
      self.default_id = default_id

   @property
   def ids(self) -> List[str]:
      remainder = sorted(i for i in self._by_id if i != self.default_id)
      return [self.default_id] + remainder

   def summaries(self) -> List[Dict[str, str]]:
      return [self._by_id[i].summary() for i in self.ids]

   def scenario(self, dataset_id: Optional[str] = None) -> Scenario:
      """The named scenario; `None` means the default.

      Raises `KeyError` for an unknown id -- the API turns that into a 404,
      the same way an unknown threat picture is already handled.
      """
      if dataset_id is None:
         dataset_id = self.default_id
      if dataset_id not in self._by_id:
         raise KeyError(
            f"Unknown dataset: '{dataset_id}'. Known: {self.ids}"
         )
      return self._by_id[dataset_id].scenario

   def __contains__(self, dataset_id: object) -> bool:
      return dataset_id in self._by_id

   def __len__(self) -> int:
      return len(self._by_id)


def _load(path: str) -> Dataset:
   try:
      scenario = load_scenario(path)
   except Exception as exc:  # noqa: BLE001 -- the point is to name the file
      raise DatasetLoadError(f"{path}: {type(exc).__name__}: {exc}") from exc
   return Dataset(id=os.path.splitext(os.path.basename(path))[0], path=path, scenario=scenario)


def build_registry(
   data_dir: str = DATA_DIR,
   default_path: Optional[str] = None,
) -> DatasetRegistry:
   """Scan `data_dir`, load every dataset, and make `default_path` the default.

   `default_path` defaults to `$CLOPT_DATA`. A path outside `data_dir` joins
   the registry under its own stem, so a one-off theater handed to the server
   on the command line is addressable like any other.
   """
   if default_path is None:
      default_path = os.environ.get("CLOPT_DATA", DEFAULT_DATA_PATH)

   paths = [
      os.path.join(data_dir, f)
      for f in sorted(os.listdir(data_dir))
      if f.endswith(".json")
   ]
   known = {os.path.realpath(p) for p in paths}
   if os.path.realpath(default_path) not in known:
      paths.append(default_path)

   datasets = [_load(p) for p in paths]
   default_id = os.path.splitext(os.path.basename(default_path))[0]
   return DatasetRegistry(datasets, default_id)
