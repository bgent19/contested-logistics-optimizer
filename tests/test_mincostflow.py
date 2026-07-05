"""Tests for the min-cost flow core.

Two of these use small graphs whose optimum was worked out by hand, so a
regression in the algorithm shows up as a concrete wrong number rather than a
vague property failure. The rest assert the structural invariants any correct
flow must satisfy.
"""

from clopt.mincostflow import MinCostFlow


def _diamond():
   # Nodes: S=0, A=1, B=2, T=3
   g = MinCostFlow(4)
   h = {}
   h["SA"] = g.add_edge(0, 1, 2, 1)
   h["SB"] = g.add_edge(0, 2, 2, 3)
   h["AT"] = g.add_edge(1, 3, 2, 1)
   h["BT"] = g.add_edge(2, 3, 2, 1)
   h["AB"] = g.add_edge(1, 2, 1, 1)
   return g, h


def test_target_flow_min_cost_is_hand_value():
   # Ship exactly 3 units S->T. Hand-computed optimum is 8.
   g, _ = _diamond()
   flow, cost = g.solve(0, 3, max_flow=3)
   assert flow == 3
   assert cost == 8


def test_min_cost_max_flow_is_hand_value():
   # Maxflow S->T is bounded by the source cut = 4; min cost to ship it = 12.
   g, _ = _diamond()
   flow, cost = g.solve(0, 3)
   assert flow == 4
   assert cost == 12


def test_flow_respects_capacity():
   g, h = _diamond()
   g.solve(0, 3)
   for name, handle in h.items():
      # Recover capacity from the forward+residual pair.
      fwd = g._forward_index[handle]
      cap_total = g.arcs[fwd].cap + g.arcs[fwd ^ 1].cap
      assert g.flow_on(handle) <= cap_total + 1e-9, name


def test_flow_conservation_at_internal_nodes():
   g, h = _diamond()
   g.solve(0, 3)
   inflow = {1: 0.0, 2: 0.0}
   outflow = {1: 0.0, 2: 0.0}
   # Edges into/out of A(1) and B(2).
   f = g.flow_on
   inflow[1] += f(h["SA"])
   outflow[1] += f(h["AT"]) + f(h["AB"])
   inflow[2] += f(h["SB"]) + f(h["AB"])
   outflow[2] += f(h["BT"])
   assert abs(inflow[1] - outflow[1]) < 1e-9
   assert abs(inflow[2] - outflow[2]) < 1e-9


def test_unreachable_sink_returns_0():
   g = MinCostFlow(3)
   g.add_edge(0, 1, 5, 1)  # no path to node 2
   flow, cost = g.solve(0, 2)
   assert flow == 0
   assert cost == 0


def test_parallel_edges_prefer_cheaper_then_spill():
   # Two parallel S->T arcs: cheap (cap 2, cost 1) and expensive (cap 5, cost 10)
   g = MinCostFlow(2)
   cheap = g.add_edge(0, 1, 2, 1)  # cheap arc
   expensive = g.add_edge(0, 1, 5, 10)  # expensive arc
   flow, cost = g.solve(0, 1, max_flow=3)
   assert flow == 3
   # 2 units cheap + 1 unit expensive = 2*1 + 1*10 = 12
   assert cost == 12
   assert g.flow_on(cheap) == 2
   assert g.flow_on(expensive) == 1