"""The Day 1 counterexample, pinned at full truth.

These are the numbers that go on the board. They live here and only here --
duplicating them at the HTTP boundary would mean one capacity edit turns the
suite red in two places, and the second red is noise.

The claims are ordered by how badly they want pinning, not by narrative order.
"""

import glob
import os

import pytest

from clopt.cli import main as cli_main
from clopt.model import Edge, Network, Node, NodeKind
from clopt.routing import naive_plan
from clopt.scenario import load_scenario
from clopt.solver import solve_allocation

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "data")
THEATER = os.path.join(DATA_DIR, "theater_sample.json")


@pytest.fixture
def theater() -> Network:
   return load_scenario(THEATER).network


def _lane(plan, src, dst):
   for l in plan.lanes:
      if (l.src, l.dst) == (src, dst):
         return l
   return None


def _source(plan, node_id):
   for s in plan.sources:
      if s.id == node_id:
         return s
   return None


def _origin_of(plan, demand_id):
   for c in plan.convoys:
      if c.dst == demand_id:
         return c.origin
   raise AssertionError(f"no convoy for {demand_id}")


# --- 1. The punchline ------------------------------------------------------
# This one can silently *invert* on a plausible capacity edit -- the naive plan
# growing more expensive than the feasible optimum -- and Day 1 would collapse
# with nothing anywhere failing. Pinned as exact values and as the inequality.

def test_naive_looks_cheaper_than_the_feasible_optimum(theater):
   naive = naive_plan(theater, risk_aversion=0.0)
   feasible = solve_allocation(theater, risk_aversion=0.0)

   assert naive.notional_cost == 1080
   assert feasible.transit_cost == 1250

   # The comparison is only honest at identical fill: both plans claim to
   # deliver every unit of demand. The naive one just cannot.
   assert naive.unserved == 0
   assert feasible.fill_rate == 1.0

   assert naive.notional_cost < feasible.transit_cost


# --- 2. The lambda=0 picture as taught -------------------------------------

def test_lambda_zero_assignment_is_the_taught_one(theater):
   plan = naive_plan(theater, risk_aversion=0.0)

   assert len(plan.convoys) == len(theater.demand_nodes()) == 3
   assert _origin_of(plan, "FOB-KILO") == "HUB-ALPHA"
   assert _origin_of(plan, "FOB-LIMA") == "HUB-BRAVO"
   assert _origin_of(plan, "FOB-MIKE") == "HUB-BRAVO"

   kilo = next(c for c in plan.convoys if c.dst == "FOB-KILO")
   assert kilo.found
   assert kilo.path == ["HUB-ALPHA", "STRAIT-3", "FOB-KILO"]
   assert kilo.quantity == 70


def test_lambda_zero_violations_are_exactly_these(theater):
   plan = naive_plan(theater, risk_aversion=0.0)

   over = {(l.src, l.dst): l.overage for l in plan.lanes if l.over}
   assert over == {
      ("HUB-BRAVO", "LANE-J2"): 30,   # 90 dispatched down a 60-unit lane
      ("LANE-J2", "FOB-MIKE"): 10,    # 40 down a 30-unit lane
   }

   bravo = _source(plan, "HUB-BRAVO")
   assert bravo.dispatched == 90 and bravo.stock == 60
   assert bravo.over and bravo.overage == 30

   # The other half of the contrast, and the reason sources are reported in
   # full: ALPHA is sitting on spare stock while BRAVO is overdrawn. An
   # over-eager violation filter drops this row and the lesson with it.
   alpha = _source(plan, "HUB-ALPHA")
   assert alpha.dispatched == 70 and alpha.stock == 120
   assert not alpha.over and alpha.overage == 0


def test_loaded_lanes_only(theater):
   plan = naive_plan(theater, risk_aversion=0.0)
   assert all(l.load > 0 for l in plan.lanes)
   # An unused lane is absent rather than present-at-zero.
   assert _lane(plan, "AIRHEAD-7", "FOB-LIMA") is None
   # ...while every supply node is present, loaded or not.
   assert {s.id for s in plan.sources} == {"HUB-ALPHA", "HUB-BRAVO"}


# --- 3. The lambda=50 stampede and the identity flip -----------------------

def test_lambda_fifty_stampedes_onto_alpha(theater):
   plan = naive_plan(theater, risk_aversion=50.0)

   assert {c.origin for c in plan.convoys} == {"HUB-ALPHA"}

   alpha = _source(plan, "HUB-ALPHA")
   bravo = _source(plan, "HUB-BRAVO")

   # The flip: at lambda=0 BRAVO is the overdrawn hub and ALPHA has slack.
   # Raise risk aversion and the identities swap -- same rule, same network.
   assert alpha.dispatched == 160 and alpha.over and alpha.overage == 40
   assert bravo.dispatched == 0 and not bravo.over

   # Everything leaves by one lane, at well over its capacity.
   assert _lane(plan, "HUB-ALPHA", "LANE-J1").load == 160
   assert _lane(plan, "HUB-ALPHA", "LANE-J1").overage == 40


def test_lambda_fifty_lima_is_a_tie_broken_on_origin_id(theater):
   """LIMA costs 24.5 from either hub at lambda=50 -- an exact tie in the
   shipped theater, not just in the synthetic fixture below. Without the
   explicit tie-break the stampede above would depend on JSON key order."""
   plan = naive_plan(theater, risk_aversion=50.0)
   lima = next(c for c in plan.convoys if c.dst == "FOB-LIMA")
   assert lima.origin == "HUB-ALPHA"
   assert lima.total_effective == 24.5


def test_raw_cost_comparison_inverts_at_high_lambda(theater):
   """The Day 1 punchline is a lambda=0 claim, and does not generalize.

   At lambda=50 the naive plan is buying expensive-but-safe air lanes, so its
   raw transit cost *exceeds* the feasible optimum's -- while still undercutting
   it on the blended yardstick it actually minimized. Pinned because the
   obvious "simplification" is to print the raw comparison at every lambda,
   which would put a false statement on the projector.
   """
   naive = naive_plan(theater, risk_aversion=50.0)
   feasible = solve_allocation(theater, risk_aversion=50.0)

   assert naive.notional_cost > feasible.transit_cost

   blended = sum(c.quantity * c.total_effective for c in naive.convoys)
   assert blended < feasible.blended_cost


# --- 4. Strictness: an exactly-saturated lane is not a violation -----------

def test_exactly_saturated_lane_is_not_over(theater):
   plan = naive_plan(theater, risk_aversion=0.0)
   lane = _lane(plan, "LANE-J2", "FOB-LIMA")
   assert lane.load == 50 and lane.cap == 50
   assert not lane.over
   assert lane.overage == 0


# --- 5. Every shipped dataset plans without raising ------------------------

@pytest.mark.parametrize(
   "path", sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))),
   ids=lambda p: os.path.splitext(os.path.basename(p))[0],
)
def test_every_dataset_plans(path):
   net = load_scenario(path).network
   for lam in (0.0, 50.0):
      plan = naive_plan(net, risk_aversion=lam)
      assert len(plan.convoys) == len(net.demand_nodes())


# --- Synthetic fixtures: branches no shipped theater reaches ---------------

def _tie_net() -> Network:
   """Two hubs, equidistant from the one demand node. Nothing in `data/`
   produces a tie at lambda=0, so the tie-break rule is otherwise untested
   until a live class hits it."""
   net = Network()
   net.add_node(Node("HUB-ZULU", NodeKind.SUPPLY, quantity=100))
   net.add_node(Node("HUB-ALPHA", NodeKind.SUPPLY, quantity=100))
   net.add_node(Node("FOB-X", NodeKind.DEMAND, quantity=10))
   net.add_edge(Edge("HUB-ZULU", "FOB-X", cap=100, cost=5, risk=0.1))
   net.add_edge(Edge("HUB-ALPHA", "FOB-X", cap=100, cost=5, risk=0.1))
   return net


def test_tie_breaks_on_origin_id_not_insertion_order():
   net = _tie_net()
   plan = naive_plan(net, risk_aversion=0.0)
   # ZULU was authored first; ALPHA wins on id. Reordering the nodes array
   # must not move the convoy.
   assert _origin_of(plan, "FOB-X") == "HUB-ALPHA"

   reordered = Network()
   for nid in ("HUB-ALPHA", "HUB-ZULU", "FOB-X"):
      reordered.add_node(net.nodes[nid])
   for e in net.edges:
      reordered.add_edge(e)
   assert _origin_of(naive_plan(reordered, risk_aversion=0.0), "FOB-X") == "HUB-ALPHA"


def _unreachable_net() -> Network:
   """One demand node no hub can reach: an island with no lane to it."""
   net = Network()
   net.add_node(Node("HUB-ALPHA", NodeKind.SUPPLY, quantity=100))
   net.add_node(Node("FOB-NEAR", NodeKind.DEMAND, quantity=10))
   net.add_node(Node("FOB-ISLAND", NodeKind.DEMAND, quantity=25))
   net.add_edge(Edge("HUB-ALPHA", "FOB-NEAR", cap=100, cost=5, risk=0.1))
   return net


def test_unreachable_demand_is_a_found_false_convoy():
   net = _unreachable_net()
   plan = naive_plan(net, risk_aversion=0.0)

   # Convoy count tracks demand-node count, so the frontend draws a third
   # node state instead of reconciling two lists.
   assert len(plan.convoys) == 2

   island = next(c for c in plan.convoys if c.dst == "FOB-ISLAND")
   assert not island.found
   assert island.path == []
   assert island.origin == ""
   assert island.quantity == 25

   assert plan.unserved == 25
   # An unroutable convoy prices at nothing -- only the reachable one counts.
   assert plan.notional_cost == 10 * 5


# --- The CLI: the output that is itself the lecture ------------------------

def test_cli_prints_the_four_sections(capsys):
   assert cli_main(["naive", "--data", THEATER, "--risk-aversion", "0"]) == 0
   out = capsys.readouterr().out

   assert "FOB-KILO" in out and "HUB-ALPHA -> STRAIT-3 -> FOB-KILO" in out
   assert "Lanes over capacity:" in out and "HUB-BRAVO -> LANE-J2" in out
   # The idle hub appears in the ledger even though it violates nothing.
   assert "Source ledger" in out and "HUB-ALPHA" in out
   assert "Notional cost: 1080.00" in out


def test_cli_does_not_claim_the_raw_comparison_at_high_lambda(capsys):
   assert cli_main(["naive", "--data", THEATER, "--lambda", "50"]) == 0
   out = capsys.readouterr().out
   assert "1250" not in out


def test_no_supply_nodes_leaves_everything_unserved():
   net = Network()
   net.add_node(Node("FOB-X", NodeKind.DEMAND, quantity=10))
   plan = naive_plan(net, risk_aversion=0.0)
   assert len(plan.convoys) == 1
   assert not plan.convoys[0].found
   assert plan.unserved == 10
   assert plan.notional_cost == 0
   assert plan.lanes == []
