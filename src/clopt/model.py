"""Domain model for contested-logistics routing.

The model is intentionally small and explicit. A `Network` is a directed graph
of `Node`s and `Edge`s. Supply nodes hold inventory, demand nodes need it, and
transshipment nodes are pure routing junctions. Every edge carries three numbers:

    cost  -- a generalized transit cost (time, fuel, lift hours -- your choice of
             unit, just be consistent). Lower is better.
    risk  -- an interdiction / attrition weight in [0, 1]. Think "expected
             fraction of this leg that is contested." Lower is safer.
    cap   -- throughput capacity for the planning window, in units (e.g. pallets,
             short tons). This makes the problem an *allocation* problem
             rather than a shortest-path problem.

A `Disruption` mutates a network (a strait gets mined, a node gets struck), which
lets us re-solve the same theater under different threat pictures and compare."

"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional


class NodeKind(str, Enum):
   SUPPLY = "supply"
   DEMAND = "demand"
   TRANSIT = "transit"

@dataclass
class Node:
   id: str
   kind: NodeKind
   # SUPPLY -> Units available
   # DEMAND -> Units required
   # TRANSIT -> ignored
   quantity: float = 0.0
   label: str = ""

   def __post_init__(self) -> None:
      if isinstance(self.kind, str):
         self.kind = NodeKind(self.kind)
      if self.quantity < 0:
         raise ValueError(f"Node {self.id}: quantity must be non-negative.")
      if self.kind is NodeKind.TRANSIT and self.quantity:
         raise ValueError(f"Node {self.id}: transit nodes carry no quantity.")


@dataclass
class Edge:
   src: str
   dst: str
   cap: float
   cost: float
   risk: float

   # If True, the edge is usable in both directions (two directed edges share
   # these attributes). Convenient for sea lanes / corridors.    
   bidirectional: bool = False

   def __post_init__(self) -> None:
      if self.cost < 0:
         raise ValueError(f"Edge {self.src} -> {self.dst}: cost must be >= 0.")
      if not (0.0 <= self.risk <= 1.0):
         raise ValueError(f"Edge {self.src} -> {self.dst}: risk must be in [0, 1].")
      if self.cap < 0:
         raise ValueError(f"Edge {self.src} -> {self.dst}: capacity must be >= 0.")
      
   def effective_cost(self, risk_aversion: float) -> float:
      """Composite edge weight: a linear blend of transit cost and risk.

      effective = cost + risk_aversion * risk

      `risk_aversion` (lambda) is the single dial that trades throughput
      cost against threat exposure. lambda = 0 routes purely on cost; large
      lambda routes purely on safety. See the README for why I keep this
      *additive* (and linear in flow) rather than using a multiplicative
      survival model.
      """
      return self.cost + risk_aversion * self.risk


@dataclass
class Network:
   nodes: Dict[str, Node] = field(default_factory=dict)
   edges: List[Edge] = field(default_factory=list)

   # ---- construction helpers -------------------------------------------
   def add_node(self, node: Node) -> None:
      if node.id in self.nodes:
            raise ValueError(f"Duplicate node id: {node.id}")
      self.nodes[node.id] = node

   def add_edge(self, edge: Edge) -> None:
      for endpoint in (edge.src, edge.dst):
         if endpoint not in self.nodes:
            raise ValueError(f"Edge references unknown node: {endpoint}")
      self.edges.append(edge)

    # ---- queries ---------------------------------------------------------
   def supply_nodes(self) -> List[Node]:
      return [n for n in self.nodes.values() if n.kind is NodeKind.SUPPLY]
   
   def demand_nodes(self) -> List[Node]:
      return [n for n in self.nodes.values() if n.kind is NodeKind.DEMAND]
   
   def total_supply(self) -> float:
      return sum(n.quantity for n in self.supply_nodes())

   def total_demand(self) -> float:
      return sum(n.quantity for n in self.demand_nodes())
   
   def directed_edges(self) -> Iterable[Edge]:
      """Expand bidirectional edges into a pair of directed edges."""
      for e in self.edges:
         yield e
         if e.bidirectional:
            yield Edge(e.dst, e.src, e.cap, e.cost, e.risk, bidirectional=False)

   def copy(self) -> "Network":
      return copy.deepcopy(self)


class DisruptionKind(str, Enum):
   REMOVE_EDGE = "remove_edge"        # capacity -> 0
   REMOVE_NODE = "remove_node"        # all incident edges -> 0 capacity
   SCALE_CAPACITY = "scale_capacity"  # cap *= factor on matching edge
   SET_RISK = "set_risk"              # risk = value on matching edge(s)
   SCALE_RISK = "scale_risk"          # risk = min(1, risk * factor)


@dataclass
class Disruption:
   kind: DisruptionKind
   src: Optional[str] = None
   dst: Optional[str] = None
   node: Optional[str] = None
   factor: float = 1.0
   value: float = 0.0
   note: str = ""

   def __post_init__(self) -> None:
      if isinstance(self.kind, str):
         self.kind = DisruptionKind(self.kind)

   def apply(self, net: Network) -> None:
      """Mutate `net` in place. Operate on a copy if you want to keep the original."""
      k = self.kind
      if k is DisruptionKind.REMOVE_NODE:
         for e in net.edges:
            if e.src == self.node or e.dst == self.node:
               e.cap = 0
         return
      # edge-targeted disruptions
      for e in net.edges:
         if e.src == self.src and e.dst == self.dst:
            if k is DisruptionKind.REMOVE_EDGE:
               e.cap = 0.0
            elif k is DisruptionKind.SCALE_CAPACITY:
               e.cap *= self.factor
            elif k is DisruptionKind.SET_RISK:
               e.risk = max(0.0, min(1.0, self.value))
            elif k is DisruptionKind.SCALE_RISK:
               e.risk = max(0.0, min(1.0, e.risk * self.factor))


@dataclass
class Scenario:
   name: str
   network: Network
   # Named bundle of disruptions, for example {"strait_closed": [Disruption(...),...]}
   threat_pictures: Dict[str, List[Disruption]] = field(default_factory=dict)
   description: str = ""

   def under(self, threat: Optional[str]) -> Network:
      """Return a fresh network with the named threat picture applied.

      `threat=None` returns the undisrupted baseline
      """
      net = self.network.copy()
      if threat is None:
         return net
      if threat not in self.threat_pictures:
         raise KeyError(
            f"Unknown threat picture: '{threat}'. "
            f"Known: {sorted(self.threat_pictures)}"
         )
      for d in self.threat_pictures[threat]:
         d.apply(net)
      return net
