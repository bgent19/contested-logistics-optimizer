# Lane crossings at projector distance — wayfinder #23

**Throwaway.** Answers: *does a lane crossing read as a crossing at the back of
the room, or as a junction that is not in the graph — and if not, what mark
fixes it?*

Run with `make proto-crossings` — prints the measurement, then opens the page.
The page is self-contained: no server, no build, no dependencies.

Descends from the [#10 legibility rig](../legibility-prototype/), reusing its
environment / CVD / distance model and its token discipline unchanged. It does
**not** relitigate the palette — #10 settled that, so only variant B's values
appear here.

## What is new

- **[#17](https://github.com/bgent19/contested-logistics-optimizer/issues/17)'s
  corrected coordinates.** `STRAIT-3` at `(300,400)`, not the `(360,400)` still
  in the #10 prototype, plus #17's twelve solved anchors — so numerals sit where
  the anchor solver puts them, not at lane midpoints.
- **The crossing set, solved at load** exactly as `graph.js` would: 8 crossings,
  with their intersection points, angles, and over/under assignment.
- **Four crossing treatments** as the switchable variants.
- **`measure.py`** — the geometry, independent of the DOM. The rig and the
  script agree crossing for crossing, which is the only reason to trust either.

## The two measurements

Both live in `measure.py`; the page shows them live in the side panel.

**Blob size.** Two strokes crossing at angle θ each smear to `w + 6.9` units at
back row, and their union is a parallelogram whose extent along each stroke is
`(w_other + 6.9) / sin θ`. Compared against a node's 60-unit diameter, because
the ticket's worry is that the merged mark reads as a junction the graph does
not have.

**Casing hole.** A knockout casing of width `w` opens a hole of `w / sin θ` in
the lane it crosses, measured along that lane. It must beat `2 × 6.9 = 13.8`.
Note the sign: the binding case is the crossing nearest **90°**, not the
shallowest — the opposite of every other quantity #17 derived, and the reason
the casing width lands where it does.

## The variants

| | Variant | The bet |
|---|---|---|
| **Z** | z-order only | Nothing. Annotations paint over lanes and that is all. What #10 already specifies, and what the frontend gets for free. |
| **K** | annotation-tier knockout | **Resolved.** A 14-unit background-coloured casing wherever an *annotation* crosses a lane — never lane-over-lane. |
| **X** | knockout at every crossing | The same casing applied lane-over-lane too, so all 8 break on every screen. Rejected: it pays on the pristine screen, where nobody is tracing anything. |
| **G** | casing along every lane | Same mark, no crossing solver at all — the cheapest possible implementation. Turn on the min-cut layer to see the bill. |
| **H** | bridge / hop | The under-lane breaks *and* the over-lane arcs, the way a road atlas draws an overpass. Rejected: costs #5 the curved-path renderer #17 already declined. |

The page opens on **K**, on the augmenting-path beat — the two crossings the
decision is actually about. Judge the rest against **Z**, not against an
imagined failure; Z was a live candidate throughout.

Every control is URL-addressable —
`?variant=K&env=washed&cvd=deutan&dist=back&preset=flowcut&cw=14` — so a
specific case can be linked rather than described. Press `x` to ring each
crossing and label its angle.

## Day 2 is not drawn

Under #17 §4's re-authored coordinates the Day-2 network is **planar as drawn:
zero crossings**. It has nothing to say about this ticket, so the rig only draws
the theater. `measure.py` still checks it, so the zero is asserted rather than
assumed.

## Not production code

No tests, no error handling, no abstractions. The annotation state (flows, the
augmenting path, the cut, naive loads) is plausible hardcoded data — except the
naive violation numbers, which are the ones the map records in #3 and #9. The
augmenting path was *chosen* to cross things: it runs `LANE-J1 → FOB-KILO`,
which crosses both AIRHEAD-7 lanes, because that is the case the ticket calls
"most likely to look like the path turning".
