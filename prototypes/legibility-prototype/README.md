# Projector legibility prototype — wayfinder #10

**Throwaway.** Answers: *what survives a washed-out classroom projector, and what
does that rule out of the layer catalog?*

Run with `make proto-legibility`, or just open `index.html` — self-contained, no
server, no build, no dependencies, both datasets inlined.

## What it draws

The ten-layer catalog from [#3](https://github.com/bgent19/contested-logistics-optimizer/issues/3),
over the authored coordinates from [#4](https://github.com/bgent19/contested-logistics-optimizer/issues/4),
under the rendering rules from [#5](https://github.com/bgent19/contested-logistics-optimizer/issues/5)
— hand-written SVG, one fixed `viewBox`, every appearance value in a `:root`
token block, JS setting only geometry, text and classes.

Three variants, `←` / `→` or the bottom bar:

| | Variant | The bet |
|---|---|---|
| **A** | Hue-primary (strawman) | One channel carries every categorical distinction. What you get by default. |
| **B** | Redundant channel | Okabe–Ito palette; nothing rests on hue alone (dash + weight + glyph + plate). Full density kept. |
| **C** | Sparse | Same palette, opposite bet: drop inactive marks to a 30% scaffold, move cap/cost/risk numerals off-canvas to a ledger, make the few remaining numerals huge. |

A and B differ **only in token values** — which is #5's claim about this
ticket's deliverable, tested. C additionally changes *structure*, and that is
the finding that one option here costs more than a retune.

## The instrumentation

The point of the rig, and the equivalent of #4's drift table — measured, not
eyeballed.

- **Projector environment.** A projector in a lit room does not dim; it *lifts
  the black floor* and loses saturation. Modelled as an affine per-channel
  transform (`ideal` / `typical` 0.14 lift / `washed` 0.32 lift). The same
  maths runs in the SVG filter and in JS, so the contrast readout describes
  what is actually on screen.
- **Colour vision.** Machado severity-1.0 matrices: deuteranopia, protanopia,
  tritanopia, achromatopsia.
- **Viewing distance.** Scale-down plus an acuity blur — front row / mid room /
  back row.
- **Contrast table.** WCAG ratio of every token against the diagram background,
  computed *after* the environment and CVD transforms, against 4.5:1 for
  numerals and 3:1 for strokes and fills.
- **Confusable pairs.** Every token pair compared by **ΔE76 in CIE Lab**, not
  by luminance ratio — luminance is hue-blind and would call green-vs-grey
  identical. Threshold ΔE < 15.
- **Type size.** Expressed as a fraction of the `viewBox` height (#5's stable
  unit, valid on unknown hardware): H/40 (2.5%) comfortable, H/50 (2.0%)
  minimum, below that laptop-only.

Every control is URL-addressable — `?variant=C&env=washed&cvd=deutan&dist=back&preset=worst`
— so a specific failure can be linked rather than described.

## Not production code

No tests, no error handling, no abstractions. The hull used for the S-side /
T-side shading is a crude star polygon, and the annotation state (flows,
residuals, cut, naive loads) is plausible hardcoded data, not computed — except
the naive violation numbers, which are the ones the map already records in #3
and #9.
