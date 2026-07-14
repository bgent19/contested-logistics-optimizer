"""End-to-end allocation tests against the shipped sample scenario.

These exercise the full path: load JSON -> apply a threat picture -> solve ->
check domain-level outcomes (fill rate, cost, risk) behave the way the model
promises.
"""

import os

from clopt.scenario import load_scenario
from clopt.solver import pareto_sweep, solve_allocation

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "theater_sample.json")


def _scenario():
    return load_scenario(os.path.abspath(DATA))


def test_baseline_meets_all_demand():
    net = _scenario().under(None)
    res = solve_allocation(net, risk_aversion=0.0)
    assert abs(res.delivered - net.total_demand()) < 1e-6
    assert abs(res.fill_rate - 1.0) < 1e-6


def test_allocation_conserves_at_demand_nodes():
    net = _scenario().under(None)
    res = solve_allocation(net, risk_aversion=2.0)
    # Inflow to each demand node should equal its requirement (demand fully met).
    demand = {n.id: n.quantity for n in net.demand_nodes()}
    inflow = {nid: 0.0 for nid in demand}
    for leg in res.active_legs():
        if leg.dst in inflow:
            inflow[leg.dst] += leg.flow
    for nid, req in demand.items():
        assert abs(inflow[nid] - req) < 1e-6, nid


def test_risk_aversion_trades_cost_for_safety():
    """As lambda rises, risk exposure must not increase and cost must not fall.

    This is the Pareto-frontier guarantee the model is built to express.
    """
    net = _scenario().under(None)
    lambdas = [0.0, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0]
    sweep = pareto_sweep(net, lambdas)
    for a, b in zip(sweep, sweep[1:]):
        # Demand stays fully met across this range, so it's a clean trade.
        assert b.risk_exposure <= a.risk_exposure + 1e-6
        assert b.transit_cost >= a.transit_cost - 1e-6


def test_zero_lambda_uses_the_dangerous_shortcut():
    net = _scenario().under(None)
    res = solve_allocation(net, risk_aversion=0.0)
    strait_flow = sum(
        l.flow for l in res.active_legs()
        if l.src == "STRAIT-3" and l.dst == "FOB-KILO"
    )
    assert strait_flow > 0  # cheapest plan exploits the chokepoint


def test_strait_mined_still_feasible_but_costlier():
    sc = _scenario()
    base = solve_allocation(sc.under(None), risk_aversion=0.0)
    mined = solve_allocation(sc.under("strait_mined"), risk_aversion=0.0)
    # Demand can still be met by rerouting...
    assert abs(mined.fill_rate - 1.0) < 1e-6
    # ...but the cheap shortcut is gone, so transit cost rises.
    assert mined.transit_cost > base.transit_cost


def test_hub_loss_forces_partial_fill():
    sc = _scenario()
    net = sc.under("bravo_struck")
    res = solve_allocation(net, risk_aversion=0.0)
    # Losing HUB-BRAVO drops supply below demand -> cannot fully fill.
    assert res.delivered <= net.total_supply() + 1e-6
    assert res.fill_rate < 1.0
