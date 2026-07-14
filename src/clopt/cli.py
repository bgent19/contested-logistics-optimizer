"""Command-line interface for the contested-logistics optimizer.

Examples
--------
    clopt info        --data data/theater_sample.json
    clopt allocate    --data data/theater_sample.json --risk-aversion 0
    clopt allocate    --data data/theater_sample.json --threat strait_mined
    clopt route       --data data/theater_sample.json --from HUB-ALPHA --to FOB-KILO --safest
    clopt sweep       --data data/theater_sample.json --lambdas 0,1,5,25,100
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from .routing import cheapest_path, safest_path
from .scenario import load_scenario
from .solver import pareto_sweep, solve_allocation
from .throughput import max_flow_min_cut
from .interdiction import budget_interdiction, min_cut_interdiction


def _load(args) -> "tuple":
   sc = load_scenario(args.data)
   net = sc.under(args.threat)
   return sc, net


def _print_allocation(res, as_json: bool) -> None:
   if as_json:
      print(json.dumps({
         "risk_aversion": res.risk_aversion,
         "delivered": res.delivered,
         "total_demand": res.total_demand,
         "fill_rate": res.fill_rate,
         "transit_cost": res.transit_cost,
         "risk_exposure": res.risk_exposure,
         "blended_cost": res.blended_cost,
         "legs": [
            {"src": l.src, "dst": l.dst, "flow": l.flow,
             "cost": l.cost, "risk": l.risk}
            for l in res.active_legs()
         ],
      }, indent=2))
      return
   print(f"Risk aversion (lambda): {res.risk_aversion:g}")
   print(f"Delivered: {res.delivered:g} / {res.total_demand:g} "
         f"demand  ({res.fill_rate * 100:.1f}% fill)")
   print(f"Transit cost:   {res.transit_cost:.2f}")
   print(f"Risk exposure:  {res.risk_exposure:.2f}")
   print(f"Blended cost:   {res.blended_cost:.2f}")
   print("\nActive legs (flow > 0):")
   print(f"  {'leg':<26}{'flow':>8}{'cost':>7}{'risk':>7}")
   for l in sorted(res.active_legs(), key=lambda x: (-x.flow, x.src)):
      leg = f"{l.src} -> {l.dst}"
      print(f"  {leg:<26}{l.flow:>8g}{l.cost:>7g}{l.risk:>7.2f}")


def cmd_info(args) -> int:
   sc = load_scenario(args.data)
   net = sc.network
   print(f"Scenario: {sc.name}")
   if sc.description:
      print(sc.description)
   print(f"\nNodes: {len(net.nodes)} Edges: {len(net.edges)}")
   print(f"Total supply: {net.total_supply():g}   "
         f"Total demand: {net.total_demand():g}")
   print("\nSupply:")
   for n in net.supply_nodes():
      print(f"  {n.id:<12} {n.quantity:g}  {n.label}")
   print("\nDemand:")
   for n in net.demand_nodes():
      print(f"  {n.id:<12} {n.quantity:g}  {n.label}")
   if sc.threat_pictures:
      print("\nThreat Pictures:")
      for name, ds in sc.threat_pictures.items():
         print(f"  {name}  ({len(ds)} disruption(s))")
   return 0


def cmd_allocate(args) -> int:
   _, net = _load(args)
   res = solve_allocation(net, risk_aversion=args.risk_aversion)
   _print_allocation(res, args.json)
   return 0


def cmd_route(args) -> int:
   _, net = _load(args)
   if args.safest:
      r = safest_path(net, args.src, args.dst)
      mode = "safest (max survival)"
   else:
      r = cheapest_path(net, args.src, args.dst, risk_aversion=args.risk_aversion)
      mode = f"cheapest (lambda={args.risk_aversion:g})"
   if args.json:
      print(json.dumps({
         "mode": mode, "found": r.found, "path": r.path,
         "total_cost": r.total_cost, "total_effective_cost": r.total_effective,
         "survival": r.survival, "hops": r.hops,
      }, indent=2))
      return 0 if r.found else 1
   if not r.found:
      print(f"No path from {args.src} to {args.dst} under current conditions.")
      return 1
   print(f"Mode: {mode}")
   print(f"Path: {'->'.join(r.path)} ({r.hops} hops)")
   print(f"Transit cost: {r.total_cost:g}")
   print(f"Survival probability: {r.survival * 100:.1f}%")
   return 0


def cmd_sweep(args) -> int:
   _, net = _load(args)
   lambdas: List[float] = [float(x) for x in args.lambdas.split(",")]
   results = pareto_sweep(net, lambdas)
   if args.json:
      print(json.dumps([
         {"risk_aversion": r.risk_aversion, "fill_rate": r.fill_rate,
         "transit_cost": r.transit_cost, "risk_exposure": r.risk_exposure}
         for r in results
      ], indent=2))
      return 0
   print("Cost / risk frontier (each row is one plan):\n")
   print(f"  {'lambda':>8}{'fill %':>9}{'transit cost':>15}{'risk exposure':>16}")
   for r in results:
      print(f"  {r.risk_aversion:>8g}{r.fill_rate * 100:>8.1f}%"
            f"{r.transit_cost:>15.2f}{r.risk_exposure:>16.2f}")
   print("\nRead it as an exchange rate: moving down the table buys lower risk "
         "exposure at higher transit cost.")
   return 0


def cmd_maxflow(args) -> int:
   _, net = _load(args)
   res = max_flow_min_cut(net, trace=getattr(args, "trace", False))
   if args.json:
      print(json.dumps({
         "max_throughput": res.value,
         "cut_capacity": res.cut_capacity,
         "source_side": res.source_side,
         "cut_lanes": [
               {"src": c.src, "dst": c.dst, "capacity": c.capacity}
               for c in res.cut_lanes
         ],
      }, indent=2))
      return 0
   if getattr(args, "trace", False):
      print("Edmonds-Karp, iteration by iteration")
      print("(BFS picks a fewest-hop augmenting path each round; ties may pick a")
      print(" different-but-valid path than a handout, so this is *a* correct run.)\n")
      for st in res.trace:
         path = " -> ".join(st.path)
         terms = ", ".join(f"{c:g}" for c in st.lane_residuals)
         print(f"Iteration {st.iteration}: {path}")
         print(f"  bottleneck = min({terms}) = {st.bottleneck:g}")
         print(f"  cumulative flow = {st.total_after:g}")
         if st.used_reverse:
               arcs = ", ".join(f"{u}->{v}" for u, v in st.used_reverse)
               print(f"  * uses reverse arc(s) {arcs} to cancel/reroute earlier flow "
                     f"-- this is where the residual graph earns its keep")
         if st.forward_residual:
               fwd = "  ".join(f"{u}->{v} {c:g}" for u, v, c in st.forward_residual)
               print(f"  residual (spare capacity): {fwd}")
         if st.reverse_residual:
               rev = "  ".join(f"{u}->{v} {c:g}" for u, v, c in st.reverse_residual)
               print(f"  residual (reverse/cancel): {rev}")
         print()
      print("No augmenting path remains -> flow is maximum.\n")
   print(f"Max throughput (s->t, units/window): {res.value:g}")
   print(f"Min-cut capacity (= max flow, by duality): {res.cut_capacity:g}")
   print("\nWitness cut -- the cheapest capacity-weighted blockade.")
   print("Sever these lanes and throughput cannot exceed the value above:")
   for c in sorted(res.cut_lanes, key=lambda x: -x.capacity):
      print(f"  {c.src} -> {c.dst:<12} capacity {c.capacity:g}")
   print("\nThis cut is the certificate: it proves no plan can move more.")
   return 0


def cmd_interdict(args) -> int:
   _, net = _load(args)
   if args.budget is None:
      inter = min_cut_interdiction(net)
      if args.json:
         print(json.dumps({
               "mode": "min_cut",
               "baseline_throughput": inter.baseline_throughput,
               "cut_capacity": inter.cut_capacity,
               "cut_lanes": [
                  {"src": c.src, "dst": c.dst, "capacity": c.capacity}
                  for c in inter.cut_lanes
               ],
         }, indent=2))
         return 0
      print("Interdiction -- capacity-weighted (polynomial, = min cut)")
      print(f"Baseline throughput: {inter.baseline_throughput:g}")
      print(f"Capacity cost to zero it out: {inter.cut_capacity:g}")
      print("Cheapest blockade lanes:")
      for c in sorted(inter.cut_lanes, key=lambda x: -x.capacity):
         print(f"  {c.src} -> {c.dst:<12} capacity {c.capacity:g}")
      return 0

   res = budget_interdiction(net, budget=args.budget, method=args.method)
   if args.json:
      print(json.dumps({
         "mode": "budget",
         "method": res.method,
         "budget": res.budget,
         "baseline_throughput": res.baseline_throughput,
         "residual_throughput": res.residual_throughput,
         "removed": [{"src": s, "dst": d} for s, d in res.removed],
         "subsets_considered": res.subsets_considered,
         "min_cut_capacity": res.min_cut_capacity,
      }, indent=2))
      return 0
   print(f"Interdiction -- budget-constrained, at most {res.budget} lane(s) "
         f"(NP-hard; method={res.method})")
   print(f"Subsets the optimum would search: {res.subsets_considered:,} "
         f"(C(|E|,1..k); this is the combinatorial cliff)")
   print(f"Baseline throughput:  {res.baseline_throughput:g}")
   print(f"Residual throughput:  {res.residual_throughput:g}  "
         f"(after removing {len(res.removed)} lane(s))")
   print("Lanes removed:")
   for s, d in res.removed:
      print(f"  {s} -> {d}")
   if not res.removed:
      print("  (none improved throughput)")
   return 0


def build_parser() -> argparse.ArgumentParser:
   p = argparse.ArgumentParser(
      prog="clopt",
      description="Contested-Logistics Routing Optimizer."
   )
   sub = p.add_subparsers(dest="command", required=True)

   def add_common(sp, threat=True):
      sp.add_argument("--data", required=True, help="Path to scenario JSON.")
      if threat:
         sp.add_argument("--threat", default=None,
                         help="Named threat picture to apply (default: baseline).")
      sp.add_argument("--json", action="store_true", help="emit JSON.")

   sp = sub.add_parser("info", help="Describe a scenario.")
   sp.add_argument("--data", required=True)
   sp.set_defaults(func=cmd_info)

   sp = sub.add_parser("allocate", help="Solve theater-wide resupply allocation.")
   add_common(sp)
   sp.add_argument("--risk-aversion", "--lambda", dest="risk_aversion",
                   type=float, default=0.0, help="Risk/cost trade dial (lambda)")
   sp.set_defaults(func=cmd_allocate)

   sp = sub.add_parser("route", help="Best single path between two nodes.")
   add_common(sp)
   sp.add_argument("--from", dest="src", required=True)
   sp.add_argument("--to", dest="dst", required=True)
   sp.add_argument("--risk-aversion", "--lambda", dest="risk_aversion",
                   type=float, default=0.0)
   sp.add_argument("--safest", action="store_true",
                   help="Maximize survival probability instead of minimizing cost.")
   sp.set_defaults(func=cmd_route)

   sp = sub.add_parser("sweep", help="Trace the cost/risk Pareto frontier.")
   add_common(sp)
   sp.add_argument("--lambdas", default="0,1,2,5,10,25,50,100",
                   help="Comma-separated lambda values.")
   sp.set_defaults(func=cmd_sweep)

   sp = sub.add_parser("maxflow",
                           help="Max throughput and the min-cut certificate (Days 2-3).")
   add_common(sp)
   sp.add_argument("--trace", action="store_true",
                  help="Print each Edmonds-Karp augmentation and the residual graph.")
   sp.set_defaults(func=cmd_maxflow)

   sp = sub.add_parser("interdict",
                        help="Adversary's cheapest blockade. Min-cut, or --budget k (Day 4).")
   add_common(sp)
   sp.add_argument("--budget", type=int, default=None,
                  help="Max lanes the interdictor may remove (omit for min-cut interdiction).")
   sp.add_argument("--method", choices=["auto", "exhaustive", "greedy"],
                  default="auto", help="Search strategy for budget interdiction.")
   sp.set_defaults(func=cmd_interdict)

   return p


def main(argv=None) -> int:
   parser = build_parser()
   args = parser.parse_args(argv)
   try:
      return args.func(args)
   except BrokenPipeError:
        # Output was piped into something that closed early (e.g. `| head`).
        # Exit silently instead of dumping a traceback.
      try:
         sys.stdout.close()
      except Exception:
         pass
      return 0 


if __name__ == "__main__":
   sys.exit(main())
   