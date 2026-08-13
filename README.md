# Contested-Logistics Routing Optimizer

> Given a network of supply and demand nodes with edge costs, interdiction risk,
> capacities, and battle-damage disruptions, compute an optimal (or, by choice,
> a deliberately risk-averse) resupply plan and show the cost/risk trade you
> are making when you pick it.

This is a small operations-research service built around a from-scratch
**minimum-cost-flow** core. It answers two questions a logistician actually
asks in a contested theater:

- **Allocation** - across *all* sources and sinks at once, how should stock move
  to meet demand at least cost, given that some lanes are cheap but dangerous?
- **Routing** - for a single convoy, what is the cheapest path, and separately,
  what is the path most likely to arrive intact?
- **Throughput & interdiction** - what is the maximum resupply rate the network
  can sustain, and which lanes would an adversary cut to choke it most cheaply?

The interesting part is not "find a shortest path." It is that in a contested
environment **there is no single optimum**. There is a frontier, and the job is
to make the exchange rate between cost and risk explicit so a commander can
*choose a point on it* instead of being handed one.

---

## Why the naive answer is wrong

Plain shortest-path planning minimizes transit cost and will happily route every
pallet through the fastest lane, which in a contested theater is often the most
dangerous one (a mined strait, a covered chokepoint). It also ignores
**capacity**: real lanes saturate, so "everyone takes the best route" is not a
feasible plan once volume matters. And it has nothing to say when a node is
struck mid-campaign.

You can run the collapse rather than take it on faith:

```bash
clopt naive    --data data/theater_sample.json --risk-aversion 0   # notional 1080
clopt allocate --data data/theater_sample.json --risk-aversion 0   # feasible  1250
```

`naive` serves each base from its own globally cheapest hub, superimposes the
routes, and counts what breaks: **HUB-BRAVO → LANE-J2** carries 90 down a
60-unit lane, and HUB-BRAVO is asked to dispatch 90 units of the 60 it holds
while HUB-ALPHA sits on 50 spare. The plan prices at **1080** against the
feasible optimum's **1250** at identical full fill — it is cheaper precisely
because it is buying capacity that does not exist. That 170 is what
buildability costs.

(The comparison is a λ=0 one. Raise risk aversion and the naive plan buys
expensive-but-safe air lanes, so its raw transit cost can pass the feasible
optimum's while still undercutting it on the blended objective it minimized.
`clopt naive` computes the comparison from whichever theater you hand it, and
declines to quote a gap when the feasible optimum cannot fill demand either.)

At λ=50 the whole theater stampedes onto HUB-ALPHA, which is then 40 units
overdrawn while HUB-BRAVO sits completely idle — the same rule, the same
network, and the opposite hub in trouble. One honest footnote for the board:
FOB-LIMA is a genuine **tie** at λ=50, costing 24.5 from either hub, and it
goes to ALPHA only because ties break on `(effective_cost, origin_id)` and
`HUB-ALPHA` sorts first. If a student asks why LIMA switched hubs, the true
answer is that it didn't have to.

This service treats the whole thing as a **capacitated min-cost flow** with a
risk-blended objective, so capacity, multi-source/multi-sink allocation, and a
tunable risk posture all fall out of one model.

---

## Quick start

**Python 3.12 or newer.** No dependencies beyond the standard library are
needed for the core and CLI, but 3.12 is the floor: it is what CI runs and what
the container is built on, so it is the only version this repo is known to work
on. If your laptop has an older Python, Option A (Docker) needs nothing
installed at all.

```bash
# Option A: Docker (builds, runs the tests, then serves the API)
docker compose up            # then open http://localhost:8000/docs

# Option B: Make
make install                 # editable install with API + test extras
make test                    # run the suite
make run                     # baseline allocation on the sample theater
make demo                    # guided tour: baseline, risk-averse, sweep, disruption
make api                     # serve REST API at http://localhost:8000/docs

# Option C: nothing installed, just Python
PYTHONPATH=src python3 -m clopt.cli allocate --data data/theater_sample.json
```

---

## The model

A `Network` is a directed graph. Every node is a **supply** point (has stock), a
**demand** point (needs stock), or a **transshipment** junction. Every edge
carries three numbers:

| field | meaning | better when |
|-------|---------|-------------|
| `cost` | generalized transit cost (time, lift, fuel, etc.) | lower |
| `risk` | interdiction/attrition weight in `[0, 1]` | lower |
| `cap`  | throughput for the planning window, in units | (a constraint) |

A **`Disruption`** mutates the network (mine a strait (`remove_edge`), strike a
port (`remove_node`), harass a lane (`scale_capacity` / `scale_risk`)) so the
same theater can be re-solved under different threat pictures and compared.

### Turning it into a flow problem

We add a super-source `S` and super-sink `T`:

```
            cap = supply_i, cost 0                 cap = demand_j, cost 0
   S  ───────────────────────────▶  (supply i)        (demand j)  ──────────────▶  T
                                         │  theater edges:              ▲
                                         │  cap, cost + λ·risk          │
                                         └──────────────────────────────┘
```

Each theater edge becomes an arc with its capacity and an **effective cost**

```
effective(e) = cost(e) + λ · risk(e)
```

A min-cost **max**-flow from `S` to `T` then ships as much as capacity allows at
the cheapest risk-blended cost. If supply < demand (or disruptions choke
throughput), the max-flow is partial and the **fill rate drops out naturally**, no special-casing.

`λ` ("risk aversion") is the single dial. `λ = 0` routes purely on cost; large
`λ` routes purely on safety.

---

## The algorithm (the core)

`src/clopt/mincostflow.py` implements **Successive Shortest Paths with Johnson
potentials**, by hand:

1. Repeatedly find the cheapest augmenting path in the residual graph and
   saturate it. Each augmentation keeps the flow min-cost for its value, so the
   final flow is optimal for the value shipped.
2. The residual graph has negative-cost back-arcs, which plain Dijkstra can't
   handle. **Johnson potentials** fix this: search on *reduced costs*
   `c'(u,v) = c(u,v) + h[u] − h[v]`, which stay non-negative, so Dijkstra is
   legal. After each search, `h[v] += dist[v]`, and `h[sink]` is exactly the
   true cost of the path just found.

Because all original edge costs are non-negative (`cost + λ·risk` with
`cost, risk ≥ 0`), potentials initialize to zero (therefore no Bellman-Ford warm-up). The
code marks the one spot you'd add it if you ever introduced genuinely negative
arcs.

Single-convoy routing (`src/clopt/routing.py`) is plain Dijkstra in two flavors:
`cheapest_path` on `cost + λ·risk`, and `safest_path`, which **maximizes
survival probability** `∏(1 − risk)` by shortest-pathing on `−log(1 − risk)`.

### Complexity

| operation | cost |
|-----------|------|
| one augmentation (one Dijkstra) | `O(E log V)` |
| full min-cost flow to value `F` (integer caps) | `O(F · E log V)` |
| single-convoy route | `O(E log V)` |

### A tradeoff worth teaching: why risk is *additive* here

The honest modeling question is whether risk should be **additive**
(`cost + λ·risk`, what the allocator uses) or **multiplicative** (survival is a
*product* of per-leg `1 − risk`, what `safest_path` uses).

- **Additive** keeps the objective **linear in flow**, which is exactly what
  min-cost flow requires and what makes the whole allocation tractable and
  **integral** (integer capacities ⇒ integer per-leg plans, convenient when a
  "unit" is an indivisible pallet). The price is that `λ` is a *posture*, not a
  physical probability.
- **Multiplicative** survival is more physically faithful for a *single* path,
  and it linearizes cleanly via `−log`. But along a multi-leg flow the
  delivered quantity *shrinks* leg by leg, which makes the objective nonlinear
  in flow and breaks the clean min-cost-flow formulation.

So the design uses additive blending for theater-wide allocation and reserves
the exact multiplicative survival model for single-convoy routing, where it is
both correct and cheap. That split is a deliberate engineering choice, for the sake of simplicity.

---

## Mapping to the algorithms unit (Days 1–4)

This repo is built to be the working companion to a four-day flow-networks unit.
Each day's idea has a concrete home in the code you can run and read.

| unit | idea | in this repo |
|------|------|--------------|
| **Day 1** | shortest path is the wrong model once capacity binds | `routing.py`: `cheapest_path` / `safest_path` are the "first instinct", and `naive_plan` builds a whole plan out of them so the collapse is computed, not asserted — `clopt naive` prints the oversubscribed lanes and the overdrawn hub |
| **Day 2** | Ford–Fulkerson / **Edmonds–Karp** max-flow on a residual graph | `maxflow.py` (BFS augmenting paths, explicit residual arcs); reproduces the unit's worked example exactly: `clopt maxflow --data data/textbook_maxflow.json` returns **7** |
| **Day 3** | **Max-Flow Min-Cut**: the cut is a certificate of optimality | `throughput.py` extracts the witness cut; `clopt maxflow` prints the lanes that prove no plan moves more |
| **Day 4** | **interdiction** - polynomial min-cut vs. NP-hard budget version | `interdiction.py`: `min_cut_interdiction` (polynomial) and `budget_interdiction` (exhaustive optimum *and* greedy heuristic, with the combinatorial subset count surfaced) |
| *sequel* | cost-aware flow the unit sets up but doesn't cover | `mincostflow.py` + `solver.py`: risk-blended **min-cost flow**, the cost/risk Pareto frontier |

The throughline matches the unit's own thesis: the same primitives (BFS, Dijkstra,
residual graphs) get reused across very different questions, and a small,
operationally reasonable change (paying per lane instead of per unit of capacity)
flips interdiction from milliseconds to NP-hard.

```bash
# Day 2-3: max throughput + the min-cut certificate
clopt maxflow   --data data/textbook_maxflow.json     # -> 7, witness cut = 7
clopt maxflow   --data data/theater_sample.json

# Day 2, live in class: print each augmentation + residual graph (incl. reverse arcs)
clopt maxflow   --data data/textbook_maxflow.json --trace

# Day 4: the adversary's cheapest blockade
clopt interdict --data data/theater_sample.json               # polynomial min-cut
clopt interdict --data data/theater_sample.json --budget 2    # NP-hard, k-edge
```

On the sample theater, a budget interdictor removing just **two** lanes drops
throughput from 260 to 60, the "which k-subset does the most damage" question
the polynomial min-cut can't answer.

---

## What it produces (sample theater)

The shipped `data/theater_sample.json` is a fictional, unclassified
island-resupply theater: two rear hubs sustaining three forward bases, with a
cheap-but-dangerous strait, a safe-but-pricey airhead, and capacity-limited
lanes.

**Baseline (`λ = 0`)** exploits the dangerous shortcut (70 units through the
strait) for 100% fill at transit cost **1250** and risk exposure **90.9**.

**Sweep the dial** and the frontier appears:

```
  lambda   fill %   transit_cost   risk_exposure
       0   100.0%        1250.00           90.90
      10   100.0%        1610.00           47.70
      25   100.0%        1755.00           37.25
     100   100.0%        1845.00           34.25
```

Read it as an exchange rate: buying the risk exposure down from 90.9 to 34.3
costs about 595 extra transit units. The commander picks the point; the tool
prices it.

**Disruptions behave the way they should:**

- `strait_mined` - the cheap chokepoint is gone, so the plan reroutes; demand is
  still 100% met, but transit cost rises to **1680**.
- `bravo_struck` - losing a hub drops supply below demand, so fill falls to
  **75%**, and the solver spends what supply remains where it does the most good.

---

## CLI

```bash
# Describe the theater
clopt info     --data data/theater_sample.json

# Theater-wide allocation (add --json for machine-readable output)
clopt allocate --data data/theater_sample.json --risk-aversion 25
clopt allocate --data data/theater_sample.json --threat strait_mined

# Day 1: the naive plan and everything it oversubscribes
clopt naive    --data data/theater_sample.json --risk-aversion 0
clopt naive    --data data/theater_sample.json --lambda 50    # the stampede onto ALPHA

# Single-convoy routing
clopt route    --data data/theater_sample.json --from HUB-ALPHA --to FOB-KILO
clopt route    --data data/theater_sample.json --from HUB-ALPHA --to FOB-KILO --safest

# Cost/risk frontier
clopt sweep    --data data/theater_sample.json --lambdas 0,5,25,100

# Max throughput + min-cut certificate (Days 2-3)
clopt maxflow  --data data/theater_sample.json

# Adversary's cheapest blockade (Day 4): min-cut, or budget-constrained
clopt interdict --data data/theater_sample.json
clopt interdict --data data/theater_sample.json --budget 2 --method exhaustive
```

(If you haven't `pip install`ed, prefix with `PYTHONPATH=src python3 -m clopt.cli`.)

## REST API

```bash
make api      # uvicorn clopt.api:app  ->  http://localhost:8000/docs
```

| endpoint | purpose |
|----------|---------|
| `GET /datasets` | the dataset menu: `id`, `name`, `description` |
| `GET /scenario` | the whole drawable theater: network, coordinates, threat pictures |
| `GET /allocate?risk_aversion=&threat=` | full allocation plan with per-leg flow |
| `GET /route?from=&to=&safest=&threat=` | single-convoy path |
| `GET /sweep?lambdas=&threat=` | cost/risk frontier rows, each with the plan's legs |
| `GET /naive?lambdas=&threat=` | Day 1's unbuildable plan, complete, one per lambda |
| `GET /maxflow?threat=` | max throughput + min-cut certificate |
| `GET /interdict?budget=&method=&threat=` | adversary's cheapest blockade |

One server serves every theater. Each endpoint above also takes an optional
`dataset=` parameter naming a dataset id -- the **filename stem** of a file in
`data/`, e.g. `dataset=textbook_maxflow` -- so switching from the textbook
network to the theater mid-class is a query parameter, not a restart. Omitting
it is exactly equivalent to naming the `CLOPT_DATA` dataset, which is also the
first entry `/datasets` returns (the rest follow alphabetically, so cycling
forward in the frontend always moves away from home). An unknown id is a 404.

Every dataset is loaded at startup, not on first request: a file that will not
load stops the server immediately and the error names the file, rather than
surfacing as a 500 halfway through a class.

Interactive Swagger docs are served at `/docs`.

### The `/scenario` payload

`/scenario` is the one endpoint a frontend draws from, so it returns the whole
picture in a single request: the summary counts, the full network with authored
coordinates, and every threat picture with its effects already computed.

```jsonc
{
  "name": "...", "description": "...",
  "node_count": 9, "edge_count": 12,
  "total_supply": 180.0, "total_demand": 160.0,
  "network": {
    "nodes": [ { "id": "HUB-ALPHA", "kind": "supply", "quantity": 120.0,
                 "label": "...", "x": 110.0, "y": 250.0 } ],
    "edges": [ { "id": "e00", "src": "HUB-ALPHA", "dst": "LANE-J1",
                 "cap": 120.0, "cost": 4.0, "risk": 0.05, "bidirectional": false } ]
  },
  "threat_pictures": {
    "strait_mined": {
      "disruptions": [ { "kind": "remove_edge", "src": "...", "dst": "...", "note": "..." } ],
      "changes":     [ { "id": "e01", "cap": 0.0, "risk": 0.45 } ]
    }
  }
}
```

Four things are worth knowing before writing a client against it:

- **There is no `threat` parameter.** The pristine network is returned always,
  and each picture's effects ship inside it, so switching threat pictures on
  screen needs no second request.
- **Edges are the *stored* edges — never reverse arcs.** A `bidirectional`
  lane is one entry here and two arcs inside the solver; deriving the reverse
  is the client's job. Shipping the expansion would draw every such lane twice.
- **The edge `id` is the stored-edge index**, zero-padded (`e00`…), so a
  dataset file's edge order is part of the contract. It is an index rather
  than a `"src>dst"` composite because the model permits parallel edges.
- **`changes` is server-computed and deliberately redundant** with the
  declarations beside it: it is each edge's *post*-disruption `cap` and `risk`,
  so a client overwrites rather than reimplementing five disruption kinds
  (including `remove_node`'s zero-every-incident-edge semantics and a risk
  clamp) in JavaScript. The `disruptions` list still ships because its `note`
  is instructor-written narration — on a projector, a caption.

One authoring trap, known and not fixed: disruption declarations match on the
**stored direction only**, so a threat picture written with `src`/`dst`
reversed matches nothing and fails silently. Authoring a new theater means
checking that each declaration actually moves an edge.

### `/sweep` and `/naive`: two arrays on one lambda index

The pair that Day 1's dial is built on. Both take the same `lambdas` parameter
with the same default, and both return one entry per value in the order asked
for — `/sweep` the *optimum* at each lambda, `/naive` the plan you get by
serving every destination from its own cheapest origin and ignoring what that
adds up to. The k-th entry of each describes the same lambda, so flipping
between the collapse and the optimum on screen is a swap at one index.

```jsonc
// GET /naive?lambdas=0,50
[ { "risk_aversion": 0.0,
    "convoys": [ { "dst": "FOB-KILO", "origin": "HUB-ALPHA", "quantity": 70.0,
                   "path": ["HUB-ALPHA", "STRAIT-3", "FOB-KILO"],
                   "total_cost": 4.0, "total_effective": 4.0,
                   "survival": 0.33, "found": true } ],
    "lanes":   [ { "src": "HUB-BRAVO", "dst": "LANE-J2",
                   "load": 90.0, "cap": 60.0, "over": true, "overage": 30.0 } ],
    "sources": [ { "id": "HUB-ALPHA", "dispatched": 70.0, "stock": 120.0,
                   "over": false, "overage": 0.0 },
                 { "id": "HUB-BRAVO", "dispatched": 90.0, "stock": 60.0,
                   "over": true, "overage": 30.0 } ],
    "notional_cost": 1080.0, "unserved": 0.0 } ]
```

Both are **stateless and prefetchable**: the whole lambda array arrives in one
call, and each `/naive` entry is a complete plan rather than a delta against
the entry before it. That is deliberate — the teaching frontend renders
synchronously, so a keypress can never wait on a fetch.

Three details a client depends on:

- **One convoy per demand node, always.** A destination nothing reaches is a
  `found: false` convoy with an empty path and `null` costs (`Infinity` is not
  JSON), its quantity counted into `unserved` — not an omitted row. So the
  convoy list is never reconciled against the node list.
- **`lanes` is loaded lanes only; `sources` is *every* supply hub**, including
  idle and healthy ones. Deliberately asymmetric: an absent lane means load
  zero and the client already has every edge from `/scenario`, but filtering
  sources to violations would throw away the idle hub standing beside the
  overdrawn one — which is half of what Day 1 is arguing.
- **`notional_cost` is named to carry its own asterisk.** It undercuts the
  feasible optimum precisely because it is buying capacity that does not exist.

---

## Project layout

```
src/clopt/
  model.py        # Node, Edge, Network, Disruption, Scenario (+ effective cost)
  mincostflow.py  # SSP min-cost flow with Johnson potentials  <- cost-aware core
  maxflow.py      # Edmonds-Karp max-flow + min-cut extraction  <- Days 2-3
  throughput.py   # network-level max-flow/min-cut in domain terms
  interdiction.py # min-cut (poly) + budget k-edge (NP-hard)    <- Day 4
  routing.py      # risk-weighted Dijkstra + max-survival path  <- Day 1
  solver.py       # build flow from a Network, decompose cost/risk, Pareto sweep
  scenario.py     # JSON load/save + validation
  datasets.py     # eager registry of every theater in data/, keyed by stem
  cli.py          # argparse CLI
  api.py          # FastAPI app
data/
  theater_sample.json    # synthetic-but-plausible scenario + threat pictures
  textbook_maxflow.json  # the unit's Day 2 worked example (max flow = 7)
tests/
  test_mincostflow.py        # hand-verified optima + flow invariants
  test_routing.py            # cheapest vs safest path behavior
  test_solver.py             # end-to-end fill/cost/risk + disruptions + Pareto
  test_maxflow_interdiction.py  # Edmonds-Karp = 7, min-cut certificate, interdiction
  test_scenarios.py          # every file in data/ loads and its threats apply
  test_api_contract.py       # HTTP contract: dataset ids, cycle order, 404s
docs/
  DESIGN_WALKTHROUGH.md  # how and in what order the repo was built, and why
```

## Testing

```bash
make test        # or: PYTHONPATH=src python3 -m pytest -q
```

The suite checks the algorithm against **hand-computed** min-cost-flow optima
(so a regression is a concrete wrong number), verifies flow conservation and
capacity invariants, and asserts the model's headline promise: as `λ` rises,
risk exposure never increases and cost never falls (a monotone Pareto frontier).

## Limitations & extensions

- Single commodity. Multi-commodity flow (distinct cargo classes competing for
  the same lanes) is the natural next step and is genuinely harder (no longer a
  pure min-cost flow).
- `λ` is a posture, not a calibrated probability (see the tradeoff note).
- Static, single-period planning. Time-expanded networks would capture
  scheduling and re-supply cadence.
- A `make demo` run and the Pareto sweep are the fastest way to see the model
  earn its keep.

## License

MIT.