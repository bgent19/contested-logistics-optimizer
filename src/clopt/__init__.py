"""Contested-Logistics Routing Optimizer (clopt).

Public API:
    model       -- Node, Edge, Network, Disruption, Scenario
    mincostflow -- MinCostFlow (the algorithmic core)
    routing     -- cheapest_path, safest_path
    solver      -- solve_allocation, pareto_sweep, AllocationResult
    scenario    -- load_scenario, save_scenario
"""

from .model import (
    Disruption,
    DisruptionKind,
    Edge,
    Network,
    Node,
    NodeKind,
    Scenario,
)
from .mincostflow import MinCostFlow
from .maxflow import EdmondsKarp
from .routing import PathResult, cheapest_path, safest_path
from .scenario import load_scenario, save_scenario, scenario_from_dict
from .solver import AllocationResult, LegFlow, pareto_sweep, solve_allocation
from .throughput import CutLane, MaxFlowResult, max_flow_min_cut
from .interdiction import (
    BudgetInterdiction,
    MinCutInterdiction,
    budget_interdiction,
    min_cut_interdiction,
)

__version__ = "0.1.0"

__all__ = [
    "Disruption",
    "DisruptionKind",
    "Edge",
    "Network",
    "Node",
    "NodeKind",
    "Scenario",
    "MinCostFlow",
    "EdmondsKarp",
    "PathResult",
    "cheapest_path",
    "safest_path",
    "load_scenario",
    "save_scenario",
    "scenario_from_dict",
    "AllocationResult",
    "LegFlow",
    "pareto_sweep",
    "solve_allocation",
    "CutLane",
    "MaxFlowResult",
    "max_flow_min_cut",
    "BudgetInterdiction",
    "MinCutInterdiction",
    "budget_interdiction",
    "min_cut_interdiction",
]
