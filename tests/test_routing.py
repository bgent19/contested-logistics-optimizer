"""Tests for single-commodity routing queries."""

import math

from clopt.model import Edge, Network, Node, NodeKind
from clopt.routing import cheapest_path, safest_path


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


def test_high_risk_aversion_takes_safe_detour():
   net = _two_route_net()
   # With lambda large, direct effective = 1 + lambda*0.5 beats detour
   # only when lambda is small. At lambda=10: direct=6, detour=6+ so need to push higher
   r = cheapest_path(net, "A", "B", risk_aversion=20.0)
   assert r.path == ["A", "C", "B"]


def test_safest_path_maximizes_survival():
   net  = _two_route_net()
   r = safest_path(net, "A", "B")
   assert r.path == ["A", "C", "B"]
   # survival = 0.99 * 0.99
   assert math.isclose(r.survival, 0.99 * 0.99, rel_tol=1e-9)


def test_unreachable_target():
   net = Network()
   net.add_node(Node("A", NodeKind.TRANSIT))
   net.add_node(Node("B", NodeKind.TRANSIT))
   # no edges
   r = cheapest_path(net, "A", "B")
   assert not r.found


def test_bidirectional_edge_is_traversable_both_ways():
   net = Network()
   net.add_node(Node("A", NodeKind.TRANSIT))
   net.add_node(Node("B", NodeKind.TRANSIT))
   net.add_edge(Edge("A", "B", cap=5, cost=2, risk=0.0, bidirectional=True))
   assert cheapest_path(net, "A", "B").found
   assert cheapest_path(net, "B", "A").found