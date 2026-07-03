"""Tests for single-commodity routing queries."""

from src.model import Edge, Network, Node, NodeKind
from src.routing import cheapest_path, safest_path


def _two_route_net():
   """A->B by a cheap-dangerous direct hop or a safe-expensive detour."""
   net = Network()
   net.add_node(Node("A", NodeKind.TRANSIT))
   net.add_node(Node("B", NodeKind.TRANSIT))
   net.add_node(Node("C", NodeKind.TRANSIT))
   # Direct: cheap but dangerous
   net.add_edge(Edge("A", "B", cap=10, cost=1, risk=0.5))
   # Detour A->C->B: expensive but safe
   net.add_edge(Edge("A", "C", cap=10, cost=3, risk=0.01))
   net.add_edge(Edge("C", "B", cap=10, cost=3, risk=0.01))
   return net


def test_cheapest_ignores_risk_when_lambda_zero():
   net = _two_route_net()
   r = cheapest_path(net, "A", "B", risk_aversion=0.0)
   assert r.found
   assert r.path == ["A", "B"]
   assert r.total_cost == 1
