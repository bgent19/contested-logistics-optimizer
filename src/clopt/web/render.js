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

import { frozen, geometry, handles, SUPER_SINK, SUPER_SOURCE } from "./graph.js";
import { edgeChanges, isRemoved, laneStates, nodeStates, NODE_STATES,
         ROW_STATES, severedNodes, SEVERED } from "./state.js";

/** The em dash an empty headline slot shows. A slot is never blank: a gap
 *  reads as a number that failed to arrive, where "—" reads as "not on this
 *  view", which is what it means. */
const EMPTY = "—";

/* What `T` says on a dataset that declares no threat picture.
 *
 * A LABELLED no-op: two of the three shipped datasets have nothing for this key
 * to cycle, so a silent decline is the common case rather than an edge, and a
 * key that does nothing in silence is indistinguishable from one that is
 * broken. It sits in the threat caption's own slot because that is the slot
 * whose subject is exactly this question. */
const NO_PICTURES = "no threat pictures in this dataset";

const GLYPH = 13;   /* half-diagonal of a lane's struck-out X, in diagram units */

/* The same X over a NODE, and a constant of its own rather than the lane's.
 *
 * A lane's X sits on an anchor with nothing behind it, where a node's has to
 * span a 30-unit disc to read as marking that node rather than as a small
 * decoration sitting on it. 21 is 0.7 of the node radius: wide enough to cross
 * the disc, short of the rim, so the white node stroke stays an unbroken circle
 * and the mark reads as struck THROUGH rather than as a broken outline. */
const NODE_GLYPH = 21;

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

/* ---- the residual marks' two chords ---------------------------------------
 * A residual arc is drawn beside its lane rather than on it, at these two
 * perpendicular offsets. Named rather than inline because the RELATIONSHIP is
 * the load-bearing part: 11 and 22 are one promotion apart, and the gap between
 * them is what forced the replace-never-add rule below.
 *
 * The plain arc sits at 11, clear of the lane's own 14-unit half-band. The
 * promotion moves it out to 22 -- in place, on the same side -- so the room
 * sees the same arc step away from the lane rather than a second arc appear
 * beside it.
 *
 * Two arcs at 11 and 22 leave 4.0 units of ground between their strokes, which
 * at the back of the room is no gap at all: they merge into one heavy mark that
 * says neither thing. That is why promotion REPLACES. It is a trap only drawing
 * reveals -- the numbers look comfortable written down.
 */
const RESIDUAL_OFFSET = 11;
const REVERSE_OFFSET = 22;

/* Which side of the lane an arc is drawn on falls out of the direction it is
 * drawn IN: the offset is taken along the left normal, so walking the lane the
 * other way puts the same positive offset on the other side. Nothing here has
 * to pick a side; the arc's own direction does it. */

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

/**
 * Where a line meets a circle, given the foot of the centre's perpendicular on
 * that line and the line's unit direction.
 *
 * The trap this exists for: `trim` above walks in from a node's CENTRE along
 * the centre line, which is the right line only for a mark drawn on it. An
 * offset chord is a different line, and trimming it by the centre-line rule
 * leaves one end floating clear of the node rim and drives the other inside the
 * disc -- visible immediately on a projector and invisible in the arithmetic.
 *
 * Half-chord is `sqrt(r^2 - d^2)` where `d` is the perpendicular distance. The
 * clamp at zero handles the tangent case, where the offset equals the radius
 * and the chord touches at a point: the mark then starts at the foot, which is
 * the right answer rather than a NaN.
 */
function circleIntersection(centre, radius, foot, direction, sign) {
  const gap = Math.hypot(foot.x - centre.x, foot.y - centre.y);
  const half = Math.sqrt(Math.max(radius * radius - gap * gap, 0));
  return {
    x: foot.x + direction.x * half * sign,
    y: foot.y + direction.y * half * sign,
  };
}

/**
 * A chord parallel to `a -> b`, offset perpendicular to it, clipped to the two
 * discs it runs between.
 *
 * Direction is the argument order: pass `(b, a, ...)` for the arc that runs the
 * other way and it lands on the other side of the lane with the same positive
 * offset, because the normal turns with it.
 */
function offsetChord(a, b, offset, startRadius, endRadius) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy) || 1;
  const direction = { x: dx / length, y: dy / length };
  const normal = { x: -direction.y, y: direction.x };
  const footA = { x: a.x + normal.x * offset, y: a.y + normal.y * offset };
  const footB = { x: b.x + normal.x * offset, y: b.y + normal.y * offset };
  const start = circleIntersection(a, startRadius, footA, direction, 1);
  const end = circleIntersection(b, endRadius, footB, direction, -1);
  return { x1: start.x, y1: start.y, x2: end.x, y2: end.y };
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

/** Write a slot's second line, or clear it. An empty qualifier collapses --
 *  unlike the number above it, an absent one has nothing to hold a place for. */
function qualify(id, text) {
  handles.qualifiers.get(id).textContent = text;
}

/**
 * The active threat picture's caption: what it is called, and what the
 * instructor wrote about it.
 *
 * The `note` on each disruption is authored narration that nothing in this repo
 * has ever drawn -- "Forward port struck; its 60 units of stock are lost to the
 * plan" -- and on a projector it is the sentence the room reads while the
 * numbers move underneath. Read off `disruptions`, which is the declaration, and
 * not off `changes`, which is the computed result and carries no words at all.
 *
 * Every note of the picture, joined: a picture is a set of disruptions and each
 * one was given its own sentence, so showing the first would silently drop the
 * author's account of the second lane that went.
 */
function threatCaption(state) {
  if (state.threatNoOp) return NO_PICTURES;
  if (!state.threat) return "";
  const picture = state.scenario.threat_pictures[state.threat];
  if (!picture) return "";
  const notes = picture.disruptions.map((one) => one.note).filter(Boolean);
  return `${state.threat} — ${notes.join(" ")}`;
}

/**
 * The headline's numbers and its one A/B pair.
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
  /* The server's figure, unadjusted, under every threat picture. What a picture
   * moves is on the wire in `changes`; total supply is not in it, because
   * removing a node zeroes its lanes and leaves its stock exactly where it was.
   * Subtracting the severed hubs here would be the frontend inventing a number
   * the API does not have -- so the total stands and the line under it says how
   * many hubs are no longer able to send any of it anywhere. */
  slot("supply", scenario.total_supply);
  qualify("supply", certificates.severed
    ? `${certificates.severed} hub(s) severed`
    : "");
  slot("demand", scenario.total_demand);
  slot("throughput", state.throughput);
  slot("bottleneck", state.bottleneck);
  slot("cut", state.cut);
  slot("interdicted", certificates.removed);
  slot("violations", certificates.violating);
  /* Day 1's second violation count, accumulated in the NODE loop from the very
   * flags that class the nodes -- the same single-rendering discipline the lane
   * counts live under. Two counts because there are two failures: a lane over
   * capacity needs a wider pipe and a hub over stock needs a different
   * assignment, and one merged number would not say which. */
  slot("overdrawn", certificates.overdrawn);
  /* Day 4's counts, per track and never per rung: the space's size attached to
   * a greedy result would claim work greedy never did. */
  slot("searched", state.search && state.search.searched);
  slot("skipped", state.search && state.search.skipped);
  /* The two tracks' residuals as one pair, `140 / 140`. Composed here because
   * it is a rendering of two numbers rather than a number -- both are read off
   * the same rung, so the pair cannot be two payloads disagreeing about one k
   * -- and shown on every dataset including the ones where the two agree.
   * Agreement absent is a blank half-screen a student reads as "greedy wasn't
   * run"; agreement stated is the control case. */
  slot("tracks",
       state.tracks ? `${state.tracks.greedy} / ${state.tracks.optimum}` : null);

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

  /* The one-sentence note. Empty on almost every beat, which is why it is a
   * slot that collapses rather than one holding an em dash like the stats
   * above: a stat's absence means "not on this view" and is worth a place-
   * holder, where a sentence's absence means there is nothing to say. */
  handles.note.textContent = state.note || "";

  /* The picture's own caption, in its own slot. Written every pass whichever
   * state it is in, so a `T` back to baseline clears the theater's narration
   * rather than leaving a sentence about mined straits over a pristine graph. */
  handles.threat.textContent = threatCaption(state);
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

  /* Which synthetic arcs this beat's path actually traverses.
   *
   * The path highlight includes them, and that is a rule rather than a detail:
   * a highlight that started at the first real node would show an augmenting
   * path beginning in the middle of the graph, with the arc it entered through
   * left dark. Read off the ordered walk rather than off the lane set, because
   * these arcs have no lane and no edge id to be in a set of. */
  const onPathTerminals = new Set();
  for (let i = 0; i + 1 < state.path.length; i += 1) {
    const from = state.path[i];
    const to = state.path[i + 1];
    if (from === SUPER_SOURCE) onPathTerminals.add(`S:${to}`);
    else if (to === SUPER_SINK) onPathTerminals.add(`T:${from}`);
  }

  for (const link of frozen.terminalLinks) {
    const key = `${link.role}:${link.nodeId}`;
    const bundle = handles.terminals.get(key);
    const node = positions.get(link.nodeId);
    const terminal = positions.get(link.role);
    /* S feeds the supply node; the demand node feeds T. The arrow points the
     * way the goods move, which is the direction the class reads off it. */
    const segment = link.role === "S"
      ? trim(terminal, node, TERMINAL_R, NODE_R + LANE_GAP)
      : trim(node, terminal, NODE_R, TERMINAL_R + LANE_GAP);
    place(bundle.line, segment);
    place(bundle.pathMark, segment);
    bundle.pathMark.classList.toggle("off", !onPathTerminals.has(key));
  }

  /* -- lanes --------------------------------------------------------------- */
  /* The certificates the headline's numbers are read off. Accumulated inside
   * the lane loop rather than computed beside it, so the count and the marked
   * rows cannot come apart. */
  const certificates = { removed: 0, violating: 0, overdrawn: 0, severed: 0 };

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

    /* -- the Flow & Cut marks ---------------------------------------------- *
     * Placed every pass and shown by class, never built here. Geometry is
     * cheap and unconditional; visibility is the only thing the beat decides.
     *
     * `promoted` is the reverse-arc moment: this beat's path walks this lane
     * AGAINST its own direction, so the traversal is not using the lane at all
     * -- it is using a residual arc, which is not a lane, and the screen has to
     * agree with the instructor saying exactly that. */
    const promoted = state.marks.against.has(edgeId);
    const residual = state.residuals.get(edgeId);
    const mark = bundle.marks;

    place(mark.residualAlong,
          offsetChord(a, b, RESIDUAL_OFFSET, NODE_R, NODE_R + LANE_GAP));
    place(mark.residualCounter,
          offsetChord(b, a, RESIDUAL_OFFSET, NODE_R, NODE_R + LANE_GAP));
    place(mark.reverseArc,
          offsetChord(b, a, REVERSE_OFFSET, NODE_R, NODE_R + LANE_GAP));

    /* PROMOTION REPLACES, NEVER ADDS -- and replaces exactly one arc.
     *
     * The promoted mark IS the counter arc, moved from 11 out to 22, so the
     * counter arc is what goes dark: the two of them at 11 and 22 leave 4.0
     * units between their strokes and merge into one heavy mark that says
     * neither thing.
     *
     * The along arc is a DIFFERENT arc on the other side of the lane, 33 units
     * away and in no danger of merging, and it carries a residual the layer is
     * on to show. Suppressing it too would take a real number off the board to
     * fix a collision it was never part of. */
    mark.residualAlong.classList.toggle(
      "off", !residual || residual.along === undefined);
    mark.residualCounter.classList.toggle(
      "off", promoted || !residual || residual.counter === undefined);
    mark.reverseArc.classList.toggle("off", !promoted);

    /* The path highlight is on the lane, at stroke 11 against the lane's 4.5,
     * so none of the lane shows through -- which is the decision. A lane walked
     * against its direction is deliberately NOT highlighted: its traversal is
     * the promoted arc beside it, and painting the lane too would say the
     * augmentation went the way the arrow points. */
    place(mark.pathMark, segment);
    mark.pathMark.classList.toggle("off", !(states["on-path"] && !promoted));

    place(mark.cutMark, segment);
    mark.cutMark.classList.toggle("off", !states["in-cut"]);

    /* -- Day 1's two lane marks -------------------------------------------- *
     * Both sit on the lane's own line, the violation wide underneath and the
     * route narrower on top, so a lane that is both shows a violation halo
     * around a route rather than one mark hiding the other.
     *
     * The route reuses `on-path`, which is not a shortcut: on Day 1 the
     * highlighted walk IS the superimposed convoy routes, and asking the same
     * question through a second lane subset would be two answers to "is this
     * lane on the walk the beat is talking about". What differs is which layer
     * shows it, and that is a fact about the catalog rather than about the
     * lane. */
    place(mark.routeMark, segment);
    mark.routeMark.classList.toggle("off", !states["on-path"]);

    place(mark.violationMark, segment);
    mark.violationMark.classList.toggle("off", !states.violating);

    /* The direction glyph's other half: a row is marked only where it is BOTH
     * on the path and running against the lane, so a forward traversal stays
     * unmarked. One lane, one row, one numeral, one glyph -- the glyph itself
     * is `content` in the stylesheet, so no second element has to exist. */
    bundle.ledgerRow.classList.toggle("against", promoted);

    /* -- the ledger's mutable cells ---------------------------------------- *
     * The three numbers a threat picture can move. The lane's identity cells
     * were written at build time and never change; these are text content on
     * cells that already exist, in a table laid out `fixed`, so nothing
     * reflows when a two-digit capacity becomes three. */
    bundle.ledgerCells.cap.textContent = String(cap);
    bundle.ledgerCells.risk.textContent = risk.toFixed(2);

    /* This beat's flow on this lane, READ off the trace and never derived. The
     * lane carries a numeral whenever the beat knows one, including a zero: a
     * saturated lane and an idle one are then told apart by what they say
     * rather than by both saying nothing, which is the whole reason the server
     * ships `flows` covering every arc instead of leaving it to be recovered
     * from the residual lists. A lane the beat has no number for shows nothing
     * at all, which is a third state and not a zero. */
    const flow = state.flows.get(edgeId);
    const flowText = flow === undefined ? "" : String(flow);
    bundle.ledgerCells.flow.textContent = flowText;
    bundle.canvasLabel.flow.textContent = flowText;
    /* The plate goes with the numeral rather than with the layer. A beat that
     * knows no flow for a lane -- Day 4 knows none for any of them, because the
     * ladder payload carries throughputs rather than per-lane flows -- would
     * otherwise leave the `flow` layer drawing twelve empty rectangles, which
     * is the unbacked-numeral bug of the opening screen with the two halves
     * swapped. */
    bundle.canvasLabel.plateFlow.classList.toggle("off", flowText === "");

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

  /* -- nodes --------------------------------------------------------------- */
  /* The hubs this picture has cut off, read out of the same `changes` block the
   * lanes above were struck from, over the frozen incidence index -- so every
   * node is judged against the same map exactly as every lane was, and the
   * question "which lanes touch this node" is answered from the topology pass
   * rather than re-derived on every keypress. */
  const severed = severedNodes(frozen.incident, changes);

  for (const [nodeId, bundle] of handles.nodes) {
    const point = positions.get(nodeId);
    bundle.circle.setAttribute("cx", point.x);
    bundle.circle.setAttribute("cy", point.y);
    bundle.id.setAttribute("x", point.x);
    bundle.id.setAttribute("y", point.y - NODE_R - 12);
    bundle.quantity.setAttribute("x", point.x);
    bundle.quantity.setAttribute("y", point.y + 6);
    shade(bundle.shade, point, state.sourceSide,
          (sides) => sides.has(nodeId));

    /* One call, two consumers -- the node's classes and the headline's `Over
     * stock` count -- exactly as `laneStates` serves the row classes and the
     * lane counts. A count that disagreed with the nodes certifying it would
     * have to disagree with itself. */
    const flags = nodeStates(state, nodeId);
    if (flags.overdrawn) certificates.overdrawn += 1;

    /* Severance is its own class rather than a fourth `NODE_STATE`, for the
     * reason recorded beside `SEVERED` in state.js: those three are per-beat
     * plan failures and this is a fact about the network under the active
     * picture.
     *
     * Counted here, from the very set that classes the node, so the figure
     * under `Supply` and the struck hubs certifying it are one rendering.
     * Supply nodes only: the count sits under the supply figure and is a claim
     * about it. A severed transit node is still greyed -- nothing can move
     * through it either, and saying so is true -- but it has no stock to
     * strand, so counting it would inflate a number about supply. */
    const isSevered = severed.has(nodeId);
    bundle.group.classList.toggle(SEVERED, isSevered);
    if (isSevered && bundle.node.kind === "supply") certificates.severed += 1;
    for (const name of NODE_STATES) {
      bundle.group.classList.toggle(name, flags[name]);
    }

    /* The ring is up whenever the plan says something about this node, and the
     * X only for the base nothing reaches. Which of the two a state gets is the
     * stylesheet's business; whether it has anything to say is this pass's. */
    const flagged = NODE_STATES.some((name) => flags[name]);
    bundle.flag.setAttribute("cx", point.x);
    bundle.flag.setAttribute("cy", point.y);
    bundle.flag.classList.toggle("off", !flagged);
    place(bundle.flagGlyphs[0], {
      x1: point.x - NODE_GLYPH, y1: point.y - NODE_GLYPH,
      x2: point.x + NODE_GLYPH, y2: point.y + NODE_GLYPH,
    });
    place(bundle.flagGlyphs[1], {
      x1: point.x - NODE_GLYPH, y1: point.y + NODE_GLYPH,
      x2: point.x + NODE_GLYPH, y2: point.y - NODE_GLYPH,
    });

    /* The supply hub's readout: what the plan asked of it against what it
     * holds. Composed here from the pair on the state, the same split the two
     * tracks live under -- the state holds the numbers the server gave and the
     * render pass decides how to write them, so the format lives in one place.
     *
     * EVERY supply node carries it, idle healthy ones included: an overdrawn
     * hub beside a hub with spare stock makes the allocation argument by
     * itself, and a readout only on the sick hub would leave the room looking
     * at a lane problem with nothing to compare it against.
     *
     * A beat that knows no allocation for this node -- which is every beat of
     * the other two views -- shows the authored quantity instead. Both spellings
     * live here rather than one here and one in the build pass: a cell two
     * modules write is a cell whose value depends on which ran last. */
    const asked = state.dispatch.get(nodeId);
    bundle.quantity.textContent = asked
      ? `${asked.dispatched}/${asked.stock}`
      : (bundle.node.quantity ? String(bundle.node.quantity) : "");
  }

  renderHeadline(state, certificates);

  /* The terminals take their side by definition rather than from the payload:
   * `source_side` lists the real nodes the source can still reach, and the two
   * derived terminals are the endpoints the partition is defined between. S is
   * on the source side of every cut and T on the sink side of every cut, so
   * reading them out of the list would be looking up a fact that is true by
   * construction -- and finding them absent from it. */
  for (const role of ["S", "T"]) {
    const bundle = handles.terminals.get(role);
    shade(bundle.shade, positions.get(role), state.sourceSide,
          () => role === "S");
  }

  /* -- the beat timeline ---------------------------------------------------- */
  handles.timeline.forEach((row, index) => {
    row.classList.toggle("current", index === state.beat);
  });

  /* -- the Pareto table's beat state ---------------------------------------- *
   * The Cost & Risk view's promoted timeline. The ACTIVE DETENT'S CONTIGUOUS
   * BLOCK is marked rather than one row, because the block is what the detent
   * is: every lambda in it returns the same pair of plans, so marking only the
   * first would say the others belong to some other point on the frontier.
   *
   * Marked from `state.detent` rather than from the beat index, so the table
   * and the beat cannot disagree -- and `null` outside this view leaves the
   * whole table unmarked, which is right: the frontier is still a fact about
   * the dataset, but no beat is standing anywhere on it. */
  handles.pareto.forEach((row) => {
    row.classList.toggle(
      "current",
      state.detent !== null && row.dataset.unit === String(state.detent),
    );
  });
}

/**
 * Put one node's disc on its side of the min cut, or on neither.
 *
 * `null` is the third state and the common one: no beat is showing a cut, so
 * neither class is written and the wash is absent rather than being drawn in
 * some neutral colour. A partition is only meaningful while there is a cut to
 * partition against.
 */
function shade(disc, point, sides, isSourceSide) {
  disc.setAttribute("cx", point.x);
  disc.setAttribute("cy", point.y);
  const on = Boolean(sides) && isSourceSide(sides);
  disc.classList.toggle("s-side", Boolean(sides) && on);
  disc.classList.toggle("t-side", Boolean(sides) && !on);
}
