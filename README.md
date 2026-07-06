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

The interesting part is not "find a shortest path." It is that in a contested
environment **there is no single optimum!**  There is a frontier, and the job is
to make the exchange rate between cost and risk explicit so a decision maker can
*choose a point on it* instead of being handed one.

---

## Why the naive answer is wrong

Plain shortest-path planning minimizes transit cost and will happily route every
pallet through the fastest lane - which in a contested theater is often the most
dangerous one (a mined strait, a covered chokepoint). It also ignores
**capacity**: real lanes saturate, so "everyone takes the best route" is not a
feasible plan once volume matters. And it has nothing to say when a node is
struck mid-campaign.

This service treats the whole thing as a **capacitated min-cost flow** with a
risk-blended objective, so capacity, multi-source/multi-sink allocation, and a
tunable risk posture all fall out of one model.

---

## The model

A `Network` is a directed graph. Every node is a **supply** point (has stock), a
**demand** point (needs stock), or a **transit** junction. Every edge
carries three numbers:

| field | meaning | better when |
|-------|---------|-------------|
| `cost` | generalized transit cost (time, lift, fuel, etc.) | lower |
| `risk` | interdiction/attrition weight in `[0, 1]` | lower |
| `cap`  | throughput for the planning window, in units | (a constraint) |

A **`Disruption`** mutates the network: mine a strait (`remove_edge`), strike a
port (`remove_node`), harass a lane (`scale_capacity` / `scale_risk`). This allows the
same theater can be re-solved under different threat pictures and compared.

### Turning it into a flow problem

I add a super-source `S` and super-sink `T`:

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
throughput), the max-flow is partial and the **fill rate drops out naturally** -
no special-casing.

`λ` ("risk aversion") is the single dial. `λ = 0` routes purely on cost; large
`λ` routes purely on safety.

---

## The algorithms

`src/clopt/mincostflow.py` implements **Successive Shortest Paths with Johnson
potentials**:

1. Repeatedly find the cheapest augmenting path in the residual graph and
   saturate it. Each augmentation keeps the flow min-cost for its value, so the
   final flow is optimal for the value shipped.
2. The residual graph has negative-cost back-arcs, which plain Dijkstra can't
   handle. **Johnson potentials** fix this: search on *reduced costs*
   `c'(u,v) = c(u,v) + h[u] − h[v]`, which stay non-negative, so Dijkstra is
   legal. After each search, `h[v] += dist[v]`, and `h[sink]` is exactly the
   true cost of the path just found.

Because all original edge costs are non-negative (`cost + λ·risk` with
`cost, risk ≥ 0`), potentials initialize to zero, so there is no Bellman-Ford warm-up required. The
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

The modeling question is whether risk should be **additive**
(`cost + λ·risk`, what the allocator uses) or **multiplicative** (survival is a
*product* of per-leg `1 − risk`, what `safest_path` uses).

- **Additive** keeps the objective **linear in flow**, which is exactly what
  min-cost flow requires and what makes the whole allocation tractable and
  **integral** (integer capacities ⇒ integer per-leg plans, convenient when a
  "unit" is an indivisible pallet). The price is that `λ` is a *posture*, not a
  physical probability.
- **Multiplicative** survival is more physically faithful for a *single* path,
  and it linearizes cleanly via `−log` but along a multi-leg flow the
  delivered quantity *shrinks* leg by leg, which makes the objective nonlinear
  in flow and breaks the clean min-cost-flow formulation.

So the design uses additive blending for theater-wide allocation and reserves
the exact multiplicative survival model for single-convoy routing, where it is
both correct and cheap. That split was an engineering choice and it is primarily
to make the project more understandable.

---

## What it produces

The shipped `data/theater_sample.json` is a fictional
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

## Project layout

```
src/clopt/
  model.py        # Node, Edge, Network, Disruption, Scenario (+ effective cost)
  mincostflow.py  # SSP min-cost flow with Johnson potentials  <- the core
  routing.py      # risk-weighted Dijkstra + max-survival path
  solver.py       # build flow from a Network, decompose cost/risk, Pareto sweep
  scenario.py     # JSON load/save + validation
  cli.py          # argparse CLI
data/
  theater_sample.json   # synthetic-but-plausible scenario + threat pictures
tests/
  test_mincostflow.py   # hand-verified optima + flow invariants
  test_routing.py       # cheapest vs safest path behavior
  test_solver.py        # end-to-end fill/cost/risk + disruptions + Pareto monotonicity
```

## License

MIT.
