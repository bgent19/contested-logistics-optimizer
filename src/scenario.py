"""Load and save `Scenario` objects as JSON.

Keeping the on-disk format human-editable matters: the whole point of a sample
dataset is that a reviewer can open it, understand the theater, and tweak it.
"""

import json
from typing import Any, Dict
from unicodedata import name

from model import Disruption, Edge, Network, Node, Scenario




def network_from_dict(data: Dict[str, Any]) -> Network:
   net = Network()
   for n in data.get("nodes", []):
      net.add_node(
         Node(
            id=n["id"],
            kind=n["kind"],
            quantity=float(n.get("quantity", 0.0)),
            label=n.get("label", "")
         )
      )
   for e in data.get("edges", []):
       net.add_edge(
           Edge(
               src=e["src"],
               dst=e["dst"],
               cap=float(e["cap"]),
               cost=float(e["cost"]),
               risk=float(e.get("risk", 0.0)),
               bidirectional=bool(e.get("bidirectional", False))
           )
       )
   return net


def scenario_from_dict(data: Dict[str, Any]) -> Scenario:
   net = network_from_dict(data["network"])
   threats: Dict[str, list] = {}
   for name, disruptions in data.get("threat_pictures", {}).items():
      threats[name] = [
         Disruption(
            kind=d["kind"],
            src=d.get("src"),
            dst=d.get("dst"),
            node=d.get("node"),
            factor=float(d.get("factor", 1.0)),
            value=float(d.get("value", 0.0)),
            note=d.get("note", "")
         )
         for d in disruptions
      ]
   return Scenario(
       name=data.get("name", ""),
       network=net,
       threat_pictures=threats,
       description=data.get("description", "")
   )


def load_scenario(path:str) -> Scenario:
   with open(path, "r", encoding="utf-8") as fh:
      return scenario_from_dict(json.load(fh))


def network_to_dict(net: Network) -> Dict[str, Any]:
   return {
      "nodes": [
         {"id": n.id, "kind": n.kind.value, "quantity": n.quantity, "label": n.label}
         for n in net.nodes.values()
      ],
      "edges": [
         {
            "src": e.src,
            "dst": e.dst,
            "cap": e.cap,
            "cost": e.cost,
            "risk": e.risk,
            "bidirectional": e.bidirectional,
         }
         for e in net.edges
      ],
   }


def save_scenario(scenario: Scenario, path: str) -> None:
   payload = {
      "name": scenario.name,
      "description": scenario.description,
      "network": network_to_dict(scenario.network),
      "threat_pictures": {
         name: [
            {
               "kind": d.kind.value,
               "src": d.src,
               "dst": d.dst,
               "node": d.node,
               "factor": d.factor,
               "value": d.value,
               "note": d.note,
            }
            for d in ds
         ]
         for name, ds in scenario.threat_pictures.items()
      },
   }

   with open(path, "w", encoding="utf-8") as fh:
      json.dump(payload, fh, indent=2)