# Layout prototype — wayfinder ticket #4

**Throwaway.** Answers one question: *where do node positions come from?* — and specifically
whether a candidate survives the constraint that the picture must **not reflow** when a
disruption removes an edge or a node, because Day 3 (min-cut) and Day 4 (interdiction)
both teach by before/after comparison.

## Run

```
make proto-layout          # or just open prototypes/layout-prototype/index.html
```

No build step, no server, no dependencies — both datasets are inlined.

## What it does

Four variants over one view, switchable with `?variant=A|B|C|D`, the floating bottom bar,
or the ← / → arrow keys:

| | Variant | Positions come from |
|---|---|---|
| **A** | Authored | hand-placed `x`/`y` in the scenario file |
| **B** | Layered | longest-path columns supply → transit → demand, barycenter sweep |
| **C** | Force-directed | Fruchterman–Reingold, 300 iterations from a random start |
| **D** | Hybrid | authored anchors (hubs, FOBs) win; junctions computed by **B** |

Controls: dataset, threat picture, **freeze layout on baseline** (compute once on the
pristine network, reuse under every threat), and baseline-position ghosts. The side panel
reports **mean node displacement vs. the baseline layout** — the pedagogical cost, in pixels.

## Measured drift (headless, same code)

Recomputing the layout on the disrupted network:

| threat | A | B | C | D |
|---|---|---|---|---|
| `strait_mined` | 0.0 | 231.8 | 302.4 | 111.4 |
| `bravo_struck` | 0.0 | 224.0 | 396.8 | 125.0 |
| `j2_pressure` | 0.0 | 0.0 | 0.0 | 0.0 |
| textbook `cut_AC` | 0.0 | 131.9 | 355.0 | 111.0 |
| textbook `cut_BD` | 0.0 | 0.0 | 294.5 | 0.0 |

Force-directed re-run with **no change to the network at all**: 239 px (theater),
425 px (textbook).

Worst individual cases, both structural rather than cosmetic:

- `strait_mined` removes `HUB-ALPHA → STRAIT-3`, so `STRAIT-3` has no inbound edge, is
  reclassified as a source, and jumps 378 px into the leftmost column.
- textbook `cut_AC` does the same to `C`, which flies 541 px across the canvas to sit
  beside `s` — on the dataset whose layout students have already seen in the notes.
- `j2_pressure` only scales a capacity, so nothing moves under any variant. Confirms the
  reflow is triggered by **topology** changes specifically.

Ticking **freeze on baseline** drives B, C and D to 0.0 px drift as well — which is the
finding: *where* coordinates come from and *when* they are computed are separate decisions.
