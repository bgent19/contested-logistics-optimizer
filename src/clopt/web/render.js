/* The one render pass. Geometry, text content and classes -- nothing else.
 *
 * Two rules hold this module in place, and both are structural rather than
 * conventional:
 *
 *   - It NEVER appends an element. Everything it touches was emitted by
 *     `graph.js` at build time and is reached through the handle map. The
 *     import direction is the enforcement: `graph.js` does not import this
 *     module, so an element created here would have to be created here, in
 *     plain sight, rather than hidden in a shared helper.
 *
 *   - It NEVER sets an appearance value. No fill, no stroke, no stroke-width,
 *     no font-size, no opacity. Those live in `style.css` behind the `:root`
 *     token block, which is what makes retuning the diagram against the real
 *     projector an edit to one stylesheet.
 *
 * Removal is a style, not a deletion: a lane cut by a threat picture keeps its
 * element and gains a class. A lane that vanishes teaches less than a lane
 * visibly struck out.
 */

import { frozen, geometry, handles } from "./graph.js";
import { edgeChanges, isRemoved } from "./state.js";

const GLYPH = 13;   /* half-diagonal of the struck-out X, in diagram units */

/* Type-dependent geometry, in diagram units.
 *
 * These four track `--type-lane-label` (15) and `--type-node-*`, and that
 * dependence is the reason they are named here instead of sitting inline. A
 * projector retune is explicitly expected to change those tokens, and the
 * plate is sized in JavaScript because only JavaScript knows how many
 * characters the text came out as -- so a type change that nobody carries over
 * to these numbers leaves every plate the wrong size around correct text,
 * which looks like a rendering bug rather than a stale constant.
 *
 * Deliberately NOT measured with `getBBox()`: the plate is `display: none`
 * until its layer is switched on, and a hidden element measures as zero.
 */
const CHAR_ADVANCE = 9;        /* mean glyph advance at --type-lane-label */
const PLATE_MIN_CHARS = 3;     /* so a one-digit label still gets a plate */
const PLATE_HALF_HEIGHT = 12;
const PLATE_HEIGHT = 24;

/* Baseline nudges: SVG `y` is a text baseline, not a centre. */
const CENTRE_BASELINE = 6;     /* drop a centred line to optical middle */
const LABEL_GAP = 12;          /* air between a node's disc and its id */

/**
 * Shorten a segment so it starts and ends clear of the discs it joins.
 *
 * Geometry, not appearance: the arrowhead has to land on the node's edge rather
 * than under its fill, or the direction of every lane is guesswork.
 */
function trim(a, b, startRadius, endRadius) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy) || 1;
  return {
    x1: a.x + (dx / length) * startRadius,
    y1: a.y + (dy / length) * startRadius,
    x2: b.x - (dx / length) * endRadius,
    y2: b.y - (dy / length) * endRadius,
  };
}

function place(line, segment) {
  line.setAttribute("x1", segment.x1);
  line.setAttribute("y1", segment.y1);
  line.setAttribute("x2", segment.x2);
  line.setAttribute("y2", segment.y2);
}

/** Repaint everything from the current state. Idempotent, and cheap enough to
 *  run on every keypress -- there is no diffing here because there is nothing
 *  to diff: a twelve-lane theater is a few dozen attribute writes. */
export function render(state) {
  if (!state.scenario) return;
  const positions = frozen.positions;
  const { NODE_R, TERMINAL_R, LANE_GAP } = geometry;
  const changes = edgeChanges(state);

  /* -- the derived terminals ---------------------------------------------- */
  for (const role of ["S", "T"]) {
    const bundle = handles.terminals.get(role);
    const point = positions.get(role);
    bundle.circle.setAttribute("cx", point.x);
    bundle.circle.setAttribute("cy", point.y);
    bundle.text.setAttribute("x", point.x);
    bundle.text.setAttribute("y", point.y + 6);
  }

  for (const link of frozen.terminalLinks) {
    const bundle = handles.terminals.get(`${link.role}:${link.nodeId}`);
    const node = positions.get(link.nodeId);
    const terminal = positions.get(link.role);
    /* S feeds the supply node; the demand node feeds T. The arrow points the
     * way the goods move, which is the direction the class reads off it. */
    const segment = link.role === "S"
      ? trim(terminal, node, TERMINAL_R, NODE_R + LANE_GAP)
      : trim(node, terminal, NODE_R, TERMINAL_R + LANE_GAP);
    place(bundle.line, segment);
  }

  /* -- lanes --------------------------------------------------------------- */
  for (const [edgeId, bundle] of handles.edges) {
    const a = positions.get(bundle.edge.src);
    const b = positions.get(bundle.edge.dst);
    const segment = trim(a, b, NODE_R, NODE_R + LANE_GAP);
    place(bundle.line, segment);

    const removed = isRemoved(changes, edgeId);
    bundle.group.classList.toggle("removed", removed);
    bundle.line.classList.toggle("removed", removed);
    bundle.ledgerRow.classList.toggle("removed", removed);

    /* The X that says "gone" sits on the anchor, not the midpoint, so it lands
     * where the lane's numerals already live rather than on a crossing. */
    const anchor = frozen.anchors.get(edgeId);
    place(bundle.glyphs[0], {
      x1: anchor.x - GLYPH, y1: anchor.y - GLYPH,
      x2: anchor.x + GLYPH, y2: anchor.y + GLYPH,
    });
    place(bundle.glyphs[1], {
      x1: anchor.x - GLYPH, y1: anchor.y + GLYPH,
      x2: anchor.x + GLYPH, y2: anchor.y - GLYPH,
    });

    /* -- the annotation tier's casing stubs ------------------------------- */
    for (const { stub, crossing } of bundle.casingStubs) {
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const length = Math.hypot(dx, dy) || 1;
      const half = crossing.length / 2;
      place(stub, {
        x1: crossing.point.x - (dx / length) * half,
        y1: crossing.point.y - (dy / length) * half,
        x2: crossing.point.x + (dx / length) * half,
        y2: crossing.point.y + (dy / length) * half,
      });
    }

    /* -- the anchor's text ------------------------------------------------- */
    const change = changes.get(edgeId);
    const cap = change ? change.cap : bundle.edge.cap;
    const risk = change ? change.risk : bundle.edge.risk;
    const { plate, stats, flow } = bundle.canvasLabel;

    stats.setAttribute("x", anchor.x);
    stats.setAttribute("y", anchor.y);
    /* Capacity, cost and risk, from the payload or from the server's `changes`
     * block -- never arithmetic performed here. */
    stats.textContent = `${cap}/${bundle.edge.cost}/${risk.toFixed(2)}`;

    flow.setAttribute("x", anchor.x);
    flow.setAttribute("y", anchor.y);

    /* The plate is sized from the text it backs, which is geometry; its fill
     * and opacity are the stylesheet's business. */
    const width = Math.max(stats.textContent.length, PLATE_MIN_CHARS) * CHAR_ADVANCE;
    plate.setAttribute("x", anchor.x - width / 2);
    plate.setAttribute("y", anchor.y - PLATE_HALF_HEIGHT);
    plate.setAttribute("width", width);
    plate.setAttribute("height", PLATE_HEIGHT);
  }

  /* -- nodes --------------------------------------------------------------- */
  for (const [nodeId, bundle] of handles.nodes) {
    const point = positions.get(nodeId);
    bundle.circle.setAttribute("cx", point.x);
    bundle.circle.setAttribute("cy", point.y);
    bundle.id.setAttribute("x", point.x);
    bundle.id.setAttribute("y", point.y - NODE_R - 12);
    bundle.quantity.setAttribute("x", point.x);
    bundle.quantity.setAttribute("y", point.y + 6);
  }
}
