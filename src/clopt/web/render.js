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
import { edgeChanges, isRemoved, laneStates, ROW_STATES } from "./state.js";

/** The em dash an empty headline slot shows. A slot is never blank: a gap
 *  reads as a number that failed to arrive, where "—" reads as "not on this
 *  view", which is what it means. */
const EMPTY = "—";

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

/* The anchor's two rows, straddling the frozen point rather than starting at
 * it: the flow numeral sits half a row above and the lane's statistics half a
 * row below, so the PAIR is centred on the point the anchor solve certified
 * clear. Hanging both rows downward would put the lower one somewhere the solve
 * never checked.
 *
 * The one geometry consequence of splitting the lane label in two, and worth
 * naming because it is a footprint change made outside the ticket that measured
 * the clearances. Two rows are not optional -- Flow & Cut shows a capacity AND
 * a flow, so the catalog requires both on screen at once, and the single-row
 * layout that preceded this drew them on top of each other. The label block now
 * spans the anchor +/-25 where it spanned +/-12, and 13 is near the minimum
 * that keeps two 24-unit plates apart.
 *
 * That still clears every distance the anchor solve enforces -- 74 from a node
 * (44 of it air beyond the disc), 74 from another anchor, 44 from a crossing.
 * What it does exceed is the 14-unit lane half-band, which governs the casing
 * width rather than the label, so nothing the crossing solve depends on moves.
 * If the retune against the real projector shows a plate crowding a lane it is
 * not attached to, this constant is the one to pull, not the anchor solve. */
const ROW_OFFSET = 13;

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

/**
 * Place one row of an anchor's stacked text, and the plate behind it.
 *
 * `text` is what the plate is sized against, which is not always the row's own
 * content -- two texts sharing a row share a plate, and it has to fit the wider
 * of them whichever is switched on. Pass `null` for the plate on the second
 * text of a shared row.
 */
function row(node, plate, anchor, offset, text) {
  node.setAttribute("x", anchor.x);
  node.setAttribute("y", anchor.y + offset);
  if (!plate) return;
  /* The plate is sized from the text it backs, which is geometry; its fill and
   * opacity are the stylesheet's business. Deliberately NOT measured with
   * `getBBox()`: the plate is `display: none` until its layer is switched on,
   * and a hidden element measures as zero. */
  const width = Math.max(text.length, PLATE_MIN_CHARS) * CHAR_ADVANCE;
  plate.setAttribute("x", anchor.x - width / 2);
  plate.setAttribute("y", anchor.y + offset - PLATE_HALF_HEIGHT);
  plate.setAttribute("width", width);
  plate.setAttribute("height", PLATE_HEIGHT);
}

/** Write one headline slot, showing the em dash rather than a gap when the
 *  active view does not own that number. */
function slot(id, value) {
  handles.headline.get(id).textContent =
    value === null || value === undefined ? EMPTY : String(value);
}

/**
 * The headline's six numbers and its one A/B pair.
 *
 * The split between the two kinds of number is the point. The struck count and
 * the violation count are *counts of a lane subset*, so they are counted from
 * the very flags that classed the rows -- the number and the lanes justifying
 * it are one rendering and cannot come apart. Throughput and cut capacity are
 * solver scalars: no subset certifies them, the server computed them, and
 * re-deriving either here would put two numbers that must be equal on the
 * dashboard by two different routes.
 */
function renderHeadline(state, certificates) {
  const scenario = state.scenario;
  slot("supply", scenario.total_supply);
  slot("demand", scenario.total_demand);
  slot("throughput", state.throughput);
  slot("cut", state.cut);
  slot("interdicted", certificates.removed);
  slot("violations", certificates.violating);

  /* The one A/B pair. This ticket owns the slot; the value belongs to whichever
   * view owns the flip, so there is deliberately no fallback pair invented
   * here. A derived statistic nobody asked for, on screen always, is exactly
   * what a fixed dashboard is meant to make impossible. The line holds its
   * space and says nothing until a view claims it. */
  const { root, label, before, after } = handles.delta;
  const pair = state.delta;
  label.textContent = pair ? pair.label : "";
  before.textContent = pair ? String(pair.before) : "";
  after.textContent = pair ? String(pair.after) : "";
  /* Shown only when the two sides actually differ. A pair reading `12 → 12` is
   * a line the instructor has to read to discover says nothing. */
  root.classList.toggle(
    "live",
    Boolean(pair) && String(pair.before) !== String(pair.after),
  );
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
  /* The certificates the headline's numbers are read off. Accumulated inside
   * the lane loop rather than computed beside it, so the count and the marked
   * rows cannot come apart. */
  const certificates = { removed: 0, violating: 0 };

  for (const [edgeId, bundle] of handles.edges) {
    const a = positions.get(bundle.edge.src);
    const b = positions.get(bundle.edge.dst);
    const segment = trim(a, b, NODE_R, NODE_R + LANE_GAP);
    place(bundle.line, segment);

    /* Capacity and risk under the active threat picture, from the server's
     * `changes` block -- never arithmetic performed here. Read before the
     * states below because cut capacity is a sum over the very lanes those
     * states mark. */
    const change = changes.get(edgeId);
    const cap = change ? change.cap : bundle.edge.cap;
    const risk = change ? change.risk : bundle.edge.risk;

    /* One call, two consumers: the row's classes and the headline's counts.
     * That is what makes a headline number and the lanes certifying it one
     * rendering rather than two that can disagree. */
    const states = laneStates(state, changes, edgeId);
    if (states.removed) certificates.removed += 1;
    if (states.violating) certificates.violating += 1;
    /* Toggling is order-independent -- a row can be in several states at once
     * and all of them are written. Which tick colour WINS when it is is source
     * order in `style.css`, and it is written down there. */
    for (const name of ROW_STATES) {
      bundle.ledgerRow.classList.toggle(name, states[name]);
    }
    /* The canvas lane carries the emphasis states too, so a pinned row and its
     * lane light up together -- the click has to be visible in the room, not
     * only on the instructor's display.
     *
     * `cold` is the scaffold tier, written onto the lane and its numerals from
     * this one call so the two can never end up on opposite sides of it. Note
     * that hot and cold are not complements: with an empty hot set neither
     * class is written anywhere, which is the pristine screen -- the graph is
     * never dimmed when the graph is itself the subject. */
    bundle.group.classList.toggle("hot", states.hot);
    bundle.group.classList.toggle("cold", states.cold);
    bundle.canvasLabel.group.classList.toggle("cold", states.cold);

    const removed = states.removed;
    bundle.group.classList.toggle("removed", removed);
    bundle.line.classList.toggle("removed", removed);

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

    /* -- the ledger's mutable cells ---------------------------------------- *
     * The three numbers a threat picture can move. The lane's identity cells
     * were written at build time and never change; these are text content on
     * cells that already exist, in a table laid out `fixed`, so nothing
     * reflows when a two-digit capacity becomes three. */
    bundle.ledgerCells.cap.textContent = String(cap);
    bundle.ledgerCells.risk.textContent = risk.toFixed(2);

    /* -- the anchor's two rows --------------------------------------------- */
    const label = bundle.canvasLabel;

    /* Capacity, cost and risk, from the payload or from the server's `changes`
     * block -- never arithmetic performed here. Two texts on the lower row,
     * one per layer, so the catalog can show a capacity beside a flow without
     * also putting cost and risk on the board. Both are written every pass
     * whichever is visible: a text that is only updated while its layer is on
     * is a text that shows a stale number the moment the layer comes back. */
    label.caps.textContent = String(cap);
    label.costrisk.textContent = `${bundle.edge.cost}/${risk.toFixed(2)}`;

    /* The lower row's plate is sized to whichever of its two texts is longer,
     * rather than to the one currently showing. Sizing it to the visible one
     * would make the plate's width depend on the layer set -- a geometry write
     * driven by appearance state, and a plate that changes size when a layer is
     * toggled on a beat that changed nothing else. */
    const statText = label.caps.textContent.length >= label.costrisk.textContent.length
      ? label.caps.textContent
      : label.costrisk.textContent;

    row(label.flow, label.plateFlow, anchor, -ROW_OFFSET, label.flow.textContent);
    row(label.caps, label.plateStat, anchor, ROW_OFFSET, statText);
    row(label.costrisk, null, anchor, ROW_OFFSET, statText);
  }

  renderHeadline(state, certificates);

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
