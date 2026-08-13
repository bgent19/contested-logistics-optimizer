"""Command-line interface for the contested-logistics optimizer.

Examples
--------
    clopt info        --data data/theater_sample.json
    clopt allocate    --data data/theater_sample.json --risk-aversion 0
    clopt allocate    --data data/theater_sample.json --threat strait_mined
    clopt naive       --data data/theater_sample.json --risk-aversion 0
    clopt route       --data data/theater_sample.json --from HUB-ALPHA --to FOB-KILO --safest
    clopt sweep       --data data/theater_sample.json --lambdas 0,1,5,25,100
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from .routing import cheapest_path, naive_plan, safest_path
from .scenario import load_scenario
from .solver import pareto_sweep, solve_allocation
from .throughput import SYNTHETIC_IDS, max_flow_min_cut
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


def cmd_naive(args) -> int:
   _, net = _load(args)
   plan = naive_plan(net, risk_aversion=args.risk_aversion)
   if args.json:
      print(json.dumps({
         "risk_aversion": plan.risk_aversion,
         "notional_cost": plan.notional_cost,
         "unserved": plan.unserved,
         "convoys": [
            {"dst": c.dst, "origin": c.origin, "quantity": c.quantity,
             "path": c.path, "total_cost": c.total_cost,
             "total_effective": c.total_effective, "survival": c.survival,
             "found": c.found}
            for c in plan.convoys
         ],
         "lanes": [
            {"src": l.src, "dst": l.dst, "load": l.load, "cap": l.cap,
             "over": l.over, "overage": l.overage}
            for l in plan.lanes
         ],
         "sources": [
            {"id": s.id, "dispatched": s.dispatched, "stock": s.stock,
             "over": s.over, "overage": s.overage}
            for s in plan.sources
         ],
      }, indent=2))
      return 0

   print(f"Naive plan -- each base served by its own cheapest hub "
         f"(lambda={plan.risk_aversion:g})\n")
   print("Convoys (one per demand node, routed as if it were the only one):")
   print(f"  {'destination':<12}{'from':<12}{'qty':>6}{'unit':>7}  path")
   for c in plan.convoys:
      if not c.found:
         print(f"  {c.dst:<12}{'--':<12}{c.quantity:>6g}{'--':>7}  "
               f"UNREACHABLE")
         continue
      print(f"  {c.dst:<12}{c.origin:<12}{c.quantity:>6g}{c.total_cost:>7g}"
            f"  {' -> '.join(c.path)}")

   violations = [l for l in plan.lanes if l.over]
   print("\nLanes over capacity:")
   if violations:
      print(f"  {'lane':<26}{'load':>7}{'cap':>7}{'over by':>9}")
      for l in sorted(violations, key=lambda x: -x.overage):
         lane = f"{l.src} -> {l.dst}"
         print(f"  {lane:<26}{l.load:>7g}{l.cap:>7g}{l.overage:>9g}")
   else:
      print("  (none -- every lane can carry what this plan puts on it)")

   print("\nSource ledger (every hub, idle ones included):")
   print(f"  {'hub':<14}{'dispatch':>9}{'stock':>7}{'over by':>9}")
   for s in plan.sources:
      flag = f"{s.overage:g}" if s.over else "-"
      print(f"  {s.id:<14}{s.dispatched:>9g}{s.stock:>7g}{flag:>9}")

   print(f"\nNotional cost: {plan.notional_cost:.2f}")
   if plan.unserved:
      print(f"Unserved demand: {plan.unserved:g} (no route exists)")
   print("Notional because this plan cannot be executed: the lanes and hubs")
   print("above are oversubscribed, so nothing here is a price anyone can pay.")
   if not plan.risk_aversion:
      # Computed, never hardcoded: this prose prints under every dataset and
      # every threat picture, and a memorized "1250" would be a lie in all
      # but one of them.
      feasible = solve_allocation(net, risk_aversion=0.0)
      print(f"The feasible optimum (`clopt allocate --risk-aversion 0`) costs "
            f"{feasible.transit_cost:.2f}.")
      if feasible.fill_rate < 1.0:
         # It is not undercutting the optimum, it is being compared against a
         # plan that gave up on some demand. Say so rather than quote a gap
         # that flatters the naive plan for the wrong reason.
         print(f"But that plan only fills {feasible.fill_rate * 100:.1f}% of "
               f"demand, so the two are not")
         print("priced over the same delivery -- no honest gap to read here.")
      else:
         gap = feasible.transit_cost - plan.notional_cost
         print(f"Both plans claim every unit of demand, so the {gap:.2f} the "
               f"naive plan saves")
         print("is bought entirely with capacity that does not exist. That gap")
         print("is what buildability costs -- and it is the whole of Day 1.")
   else:
      # At lambda > 0 the naive plan is routing on cost + lambda*risk, so
      # its *raw* transit cost can exceed the feasible optimum's while it
      # still undercuts on the blended yardstick it actually minimized.
      # Pointing at the raw numbers here would state a false comparison.
      print("At lambda > 0 compare blended costs, not this raw one: the naive")
      print("plan minimized cost + lambda*risk, so its transit cost alone can")
      print("read higher than a feasible plan's while still being unbuildable.")
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


def _real_lanes(arcs):
   """Trace arcs a student should see: real endpoints, printable numbers.

   The trace ships complete -- synthetic terminals named, unbounded residuals
   carried as `None` -- because the API's consumer draws all of it. The
   classroom text wants neither: a super-source arc is scaffolding, and `inf` is
   not a capacity anyone writes on a board. So the narrowing lives here, at the
   point of display, rather than in the data layer where it used to cost the
   drawing consumer its alignment. Takes (u, v) pairs or (u, v, value) triples.
   """
   return [arc for arc in arcs
           if arc[0] not in SYNTHETIC_IDS and arc[1] not in SYNTHETIC_IDS
           and (len(arc) < 3 or arc[2] is not None)]


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
         if st.iteration == 0:
               # The pre-augmentation snapshot exists so a drawing consumer has
               # a "before" for iteration 1. Nobody says "iteration 0" aloud.
               continue
         path = " -> ".join(n for n in st.path if n not in SYNTHETIC_IDS)
         terms = ", ".join(f"{c:g}" for c in st.lane_residuals if c is not None)
         print(f"Iteration {st.iteration}: {path}")
         print(f"  bottleneck = min({terms}) = {st.bottleneck:g}")
         print(f"  cumulative flow = {st.total_after:g}")
         used_reverse = _real_lanes(st.used_reverse)
         if used_reverse:
               arcs = ", ".join(f"{u}->{v}" for u, v in used_reverse)
               print(f"  * uses reverse arc(s) {arcs} to cancel/reroute earlier flow "
                     f"-- this is where the residual graph earns its keep")
         forward_residual = _real_lanes(st.forward_residual)
         if forward_residual:
               fwd = "  ".join(f"{u}->{v} {c:g}" for u, v, c in forward_residual)
               print(f"  residual (spare capacity): {fwd}")
         reverse_residual = _real_lanes(st.reverse_residual)
         if reverse_residual:
               rev = "  ".join(f"{u}->{v} {c:g}" for u, v, c in reverse_residual)
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

   sp = sub.add_parser("naive",
                       help="The Day 1 counterexample: cheapest-path-per-base, "
                            "and what it oversubscribes.")
   add_common(sp)
   sp.add_argument("--risk-aversion", "--lambda", dest="risk_aversion",
                   type=float, default=0.0, help="Risk/cost trade dial (lambda)")
   sp.set_defaults(func=cmd_naive)

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
   