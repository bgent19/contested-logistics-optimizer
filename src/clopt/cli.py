"""Command-line interface for the contested-logistics optimizer.

Examples
--------
    clopt info        --data data/theater_sample.json
    clopt allocate    --data data/theater_sample.json --risk-aversion 0
    clopt allocate    --data data/theater_sample.json --threat strait_mined
    clopt route       --data data/theater_sample.json --from HUB-ALPHA --to FOB-KILO --safest
    clopt sweep       --data data/theater_sample.json --lambdas 0,1,5,25,100
"""

import argparse
import json
import sys

from .routing import cheapest_path, safest_path
from .scenario import load_scenario
from .solver import solve_allocation



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
   # Implementation for sweep command
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

   return p





def main(argv=None) -> int:
   parser = build_parser()
   args = parser.parse_args(argv)
   return args.func(args)


if __name__ == "__main__":
   sys.exit(main())