/* The single app-state object, and the only functions allowed to change it.
 *
 * One object, mutated in place, read by the render pass. Not a store, not
 * events, not a framework: the whole application is a keypress that changes a
 * field and then repaints, and anything more would be machinery the class never
 * sees.
 *
 * The rule this module exists to hold: **no client-side disruption arithmetic,
 * ever.** Mutated capacities and risks come from the server's `changes` block
 * and are looked up here, never recomputed. The alternative is reimplementing
 * five disruption kinds in JavaScript -- including remove-node's
 * zero-every-incident-edge semantics and a risk clamp -- where a divergence
 * puts a capacity on the projector that the API disagrees with, mid-class, with
 * nothing raised anywhere.
 */

import { layersForView, VIEWS } from "./views.js";

export const state = {
  /** Dataset id currently drawn; `null` until the first load. */
  dataset: null,

  /**
   * Every dataset id, in the server's own cycle order.
   *
   * `/datasets` answers default-first then alphabetical, and that order is the
   * cycle: **`D` opens on the default and moves away from it**, so at two
   * datasets pressing it twice brings the instructor home. Sorting here would
   * be a second opinion about an order the server already holds.
   */
  datasets: [],

  /** The `/scenario` payload, verbatim. */
  scenario: null,
  /** Active view id. */
  view: VIEWS[0].id,
  /* Active layer ids, opening on the first view's entry set rather than empty.
   * A blank set here is not a neutral starting point -- it is the one layer
   * state the catalog forbids read from the other end, and the page would open
   * on a diagram with nothing drawn over it and no beat responsible for that.
   *
   * DERIVED, not authored: rebuilt on every beat from the view's entry table,
   * the beat's own overrides and `layerOverrides` below, in that order. Nothing
   * outside this module may write to it -- see `toggleLayer`. */
  layers: layersForView(VIEWS[0].id),

  /**
   * The layers the instructor has switched by hand, `{layerId: on}`.
   *
   * Only the ones actually touched, so a view's entry table can change under a
   * running class without the untouched layers being pinned to whatever they
   * happened to be. Layer toggles are pointer-only and this is what makes them
   * durable: the resolved set is rebuilt every beat, and without a record of
   * the hand's intent a toggle would last exactly one keypress. `R` clears it,
   * and `R` alone.
   */
  layerOverrides: new Map(),
  /** Active threat picture name, or `null` for the pristine network. */
  threat: null,

  /**
   * The threat picture each dataset was last left on, `{datasetId: name|null}`.
   *
   * **The threat picture is per-dataset state**, which is what makes the Day 2
   * excursion survivable: park on `strait_mined`, press `D` to show the same
   * beat on the textbook network, press `D` back, and the theater is still
   * under the picture it was left under. A single global field would either
   * carry a name into a dataset that never declared it -- every lookup coming
   * back undefined, a pristine network the panel claims is under threat -- or
   * drop the picture permanently on the way out.
   *
   * A picture name is only meaningful within one dataset, exactly like an edge
   * id, so `restoreThreat` checks the remembered name against the target's own
   * list rather than trusting it.
   */
  threatByDataset: new Map(),

  /**
   * Whether the last `T` had nothing to cycle. TRANSIENT.
   *
   * `T` on a dataset with no threat pictures is a *labelled* no-op, because a
   * key that silently does nothing is a key that looks broken -- and two of the
   * three shipped datasets declare no picture at all, so this is the common
   * case rather than a defensive branch.
   *
   * Cleared by `resolveBeat` with everything else derived, which is the right
   * lifetime: the label belongs to the keypress that produced it, and one still
   * on screen three beats later would be claiming something about the beat
   * under it instead.
   */
  threatNoOp: false,

  /**
   * Index into the active view's spine. See the beat engine below.
   *
   * The ONE number the keyboard moves, and the one every other field on this
   * object is derived from. It is an index rather than a cursor for a reason:
   * `setBeat` rebuilds everything below from scratch, so a beat renders
   * identically whether it was reached by stepping forward, stepping back, or
   * jumping to it cold.
   */
  beat: 0,

  /**
   * Per-view memory, `{viewId: {beat, overrides}}`.
   *
   * Views are jumpable in any order and **each remembers its own state**: Flow
   * & Cut stays parked on augmentation 3 while the instructor detours into
   * another view to answer a question and comes back. Rebuilding Edmonds-Karp
   * state live mid-sentence is the most expensive recovery in the unit, and it
   * is also the most likely one.
   */
  views: {},

  /* ---- the lane subsets the panel and the canvas both read ----------------
   * Three of the panel's apparent content shapes were never components. The
   * cut's certifying lane list and the interdicted subset are *subsets of the
   * lanes*, so they live here as sets of edge ids and are projected onto the
   * one ledger row as classes -- never as a second list beside it. Otherwise
   * the same lane sits in the panel twice, in two renderings that can
   * disagree.
   *
   * Filled by the view tickets (#42-#44). There is deliberately no `removed`
   * set: a threat picture's removals are not a set anybody assigns, they are
   * read out of the server's `changes` block by `isRemoved`. `struck` below is
   * the other source of the same row state and is a set, because a blockade IS
   * a lane subset the beat names -- off the server's ladder payload, never
   * chosen here. */
  marks: {
    onPath: new Set(),     /* the augmenting path of the current beat */
    inCut: new Set(),      /* the lanes certifying the min cut */
    violating: new Set(),  /* lanes the naive plan overloads */
    hot: new Set(),        /* whatever the current beat is talking about */
    /* The blockade this beat draws: the lanes an interdiction took away.
     * Projected onto the SAME `.removed` row state a threat picture's removals
     * wear, because on screen they are the same fact -- this lane is gone --
     * and a second class would spend a channel to say it twice. Only one
     * blockade is ever drawn, which is what keeps that true. */
    struck: new Set(),
    /* Lanes this beat's path traverses AGAINST their own direction -- the
     * reverse-arc moment. Not a sixth row state: it is a modifier on `on-path`
     * and never appears without it, which is what keeps a forward traversal
     * unmarked. It drives two things from one set, so the ledger's glyph and
     * the canvas's promoted arc can never disagree about which way a lane was
     * walked. */
    against: new Set(),
  },

  /* ---- the node subsets, which are NOT lane subsets ------------------------
   * Day 1's second failure lives here, and it lives in its own object rather
   * than as three more sets in `marks` because that is the whole point of it:
   * an over-subscribed lane is a too-small pipe and an over-drawn hub is a bad
   * ASSIGNMENT, and the room has to see two structurally different failures
   * rather than two shades of one. A node subset beside the lane subsets is
   * what makes that structural instead of chromatic.
   *
   * All three are filled by the Cost & Risk spine off the naive plan's own
   * flags, and every one of them is READ: `over` is a property in the core and
   * a plain field on the wire precisely so that no client ever compares a load
   * against a capacity itself. */
  nodes: {
    /* Supply hubs asked to dispatch past their stock. */
    overdrawn: new Set(),
    /* Demand nodes no convoy reaches at all -- the `found: false` case. */
    unreachable: new Set(),
    /* Demand nodes served, but only by a plan that cheats: their convoy's
     * origin is overdrawn, or its route crosses an over-capacity lane. */
    illegal: new Set(),
  },

  /**
   * What each supply hub was asked for against what it holds, `nodeId ->
   * {dispatched, stock}`.
   *
   * EVERY supply node, including the idle healthy ones, and that is the
   * argument rather than a completeness reflex: an overdrawn hub sitting beside
   * a hub with spare stock says "this is an allocation error" without the
   * instructor having to say it. Filtered to the violating hubs, the screen
   * shows a lane problem and nothing to compare it against.
   *
   * A pair of numbers rather than the composed string, exactly like `tracks`
   * above: the state holds what the server said and the render pass decides how
   * to write it, so the formatting lives in one place.
   */
  dispatch: new Map(),

  /**
   * Which Pareto detent the current beat sits in, 1-based, or `null`.
   *
   * The one thing the promoted Pareto table needs that a lane subset cannot
   * carry: the table's rows are lambdas and the beats are detents, so marking
   * the active detent's contiguous block means knowing which block that is.
   * Set by the beat rather than derived in the render pass, so the marked rows
   * and the beat on screen are one decision.
   */
  detent: null,

  /**
   * One sentence for the headline, or `null`.
   *
   * The slot a degenerate view x dataset combination speaks through. A
   * combination is LABELLED, not struck: striking it would be view-aware
   * behaviour, which is the hidden modality the key assignments were designed
   * to avoid. Deliberately not the A/B pair's label -- that pair means "these
   * two numbers differ", and a sentence in it would claim a comparison nobody
   * made.
   */
  note: null,


  /* ---- the current beat's slice of the trace ------------------------------
   * Both are READ off the server's trace and never derived here. `cap - flow`
   * is the subtraction this pair exists to make unnecessary: one line, correct
   * on the happy path, and silently disagreeing with the API the moment a
   * threat picture or a rounding rule moves underneath it.
   *
   * Set by a beat's `apply` and cleared by `resolveBeat` along with everything
   * else derived, so a beat renders identically however it was reached. */

  /** `edgeId -> flow` at this beat, covering every lane including saturated
   *  ones -- which the residual lists cannot say, because they drop an arc the
   *  moment it saturates. */
  flows: new Map(),

  /** `edgeId -> {forward, reverse}` residual capacity at this beat. A missing
   *  side means no residual arc in that direction, not a zero to draw. */
  residuals: new Map(),

  /** The bottleneck of the augmentation being proposed, or `null`. */
  bottleneck: null,

  /**
   * The augmenting path of this beat as the server named it: node ids, super-
   * source first and super-sink last, or empty.
   *
   * Kept as the raw node list beside `marks.onPath` rather than instead of it,
   * because the two answer different questions. The ledger needs the set of
   * LANES; the canvas needs the ORDERED walk, terminals included -- and the
   * terminal arcs have no lane and no edge id, so a set of edge ids cannot
   * describe them. Dropping them is what once made a path appear to begin in
   * the middle of the graph.
   */
  path: [],

  /** The lane pinned hot by a click, or `null`. See `pinLane`. */
  pinned: null,

  /* The two solver scalars, both from the server and neither derived here.
   *
   * `cut` is deliberately NOT summed out of `marks.inCut` in the render pass,
   * though it could be. Max-flow/min-cut says it must equal `throughput`, and
   * two numbers that must be equal, computed two different ways, one slot
   * apart on the instructor's dashboard, is a contradiction waiting for a
   * projector. The Flow & Cut view must set this and `marks.inCut` from ONE
   * `/maxflow` response, which is what keeps the number and the lanes
   * certifying it a single rendering. */
  throughput: null,
  cut: null,

  /**
   * A rung's two residual throughputs, `{greedy, optimum}`, or `null`.
   *
   * The pair is the point, and it is a pair on every dataset including the ones
   * where the two agree: the theater reads `140 / 140`, `60 / 60`, `0 / 0`.
   * Agreement STATED is the control case -- a rung with one number on screen is
   * read as "greedy wasn't run", and the theater's greedy correctness stops
   * looking like a theorem about the network's shape and starts looking like
   * luck.
   *
   * Both numbers come off the same rung of one payload, so the pair cannot be
   * two fetches disagreeing about the same k.
   */
  tracks: null,

  /**
   * The subsets one track evaluated and the remainder of the space it did not,
   * `{searched, skipped}`, or `null`.
   *
   * Per track and never per rung: `subsets_total` attached to a greedy result
   * is a false claim about work greedy never did. The beat showing greedy's
   * blockade shows greedy's counts, and the beat showing the optimum's shows
   * the optimum's.
   */
  search: null,

  /**
   * The node ids on the source side of the min cut, or `null` when no beat is
   * showing a cut.
   *
   * A set of NODES rather than the lanes, because the certificate is a
   * partition of the graph: the lane list is what the partition implies, not
   * the other way round, and shading the two sides is what stops the cut
   * reading as an arbitrary set of marked lanes. Server-computed and read --
   * `source_side` off the same `/maxflow` response that carried `cut`.
   */
  sourceSide: null,

  /**
   * The one A/B headline pair: `{label, before, after}`, or `null`.
   *
   * One pair, and no per-lane delta column anywhere. The two states are never
   * simultaneously visible by design, so a per-lane before/after would put a
   * number from the *invisible* state back on screen -- the rejected ghost
   * overlay re-entering through the panel's door. One pair the instructor can
   * say out loud beats twelve they cannot.
   */
  delta: null,
};

export function setScenario(payload) {
  state.scenario = payload;
}

export function setDataset(datasetId) {
  state.dataset = datasetId;
  /* An edge id is only meaningful within one dataset -- `e03` is a different
   * lane in every file -- so nothing keyed by edge id survives the switch.
   * That is every lane subset, not just the pin: a stale `inCut` would mark
   * rows in the new theater that certify a cut of the old one. */
  clearPin();
  for (const set of Object.values(state.marks)) set.clear();
  /* The node subsets go with the lane subsets, for the same reason: a node id
   * is only meaningful within one dataset, and a stale `overdrawn` would flag a
   * hub of the new theater on the strength of the old one's allocation. */
  for (const set of Object.values(state.nodes)) set.clear();
  state.dispatch.clear();
}

/* ---- the beat engine ------------------------------------------------------
 *
 * Every view has an ordered spine of beats, and in all three the beats come in
 * `[proposal, consequence]` pairs -- so `->` always means *"and here's what
 * that does"* and the room learns the rhythm. A beat is a plain record:
 *
 *   {unit, phase, label, apply}
 *
 * `unit` is the coarse step the instructor names out loud -- augmentation 3,
 * budget level 2, Pareto detent 4 -- and `phase` is `"a"` or `"b"` within it.
 * `apply` is optional and receives this state object; it is where a view's
 * ticket puts the marks, the headline numbers and any layer overrides that
 * beat carries.
 *
 * **`setBeat` is pure, synchronous and idempotent, and that is structural
 * rather than a promise.** It resets every derived field before applying the
 * beat, so no beat can depend on having passed through its predecessor. Which
 * is what forces the prefetch rule the whole spec keeps arriving at:
 * ANYTHING A KEYPRESS CAN REACH IS FETCHED BEFORE THE FIRST KEYPRESS, and a
 * spine is installed complete or not at all. A beat that had to fetch could not
 * be synchronous, and a beat that is not synchronous cannot be stepped
 * backwards through at speaking pace.
 *
 * Ends never wrap. Leaning on a key must not silently restart the story.
 */

/** Installed spines, `{viewId: [beat, ...]}`. Filled by #42-#44. */
const SPINES = new Map();

/**
 * The spine a view falls back to before its ticket installs one.
 *
 * One beat, which is the view's entry state -- so the keyboard is live and
 * every key is a legal no-op from the first paint, rather than a set of keys
 * that throw until three more tickets land.
 */
const ENTRY_SPINE = [{ unit: 0, phase: "a", label: "Entry" }];

/** The active view's spine, or another view's if asked for one by id. */
export function spine(viewId = state.view) {
  return SPINES.get(viewId) || ENTRY_SPINE;
}

/**
 * A beat index the given view's spine actually has, by clamping.
 *
 * The one place "carry the beat index across, as far as it still goes" is
 * written down. Every ladder in this application is derived from data -- the
 * augmentation count, the interdiction rungs, the Pareto detents -- so a spine's
 * length moves under the instructor whenever the dataset or the threat picture
 * does, and clamping is what keeps the render pure across that move rather than
 * leaving the index pointing past the end.
 */
function clampToSpine(beat, viewId = state.view) {
  return Math.min(Math.max(beat, 0), spine(viewId).length - 1);
}

/**
 * Install a view's whole spine, prefetched and complete.
 *
 * Clamps rather than resets the beat index, so re-installing a spine -- which
 * is what a dataset switch does -- lands the instructor on the same step of the
 * other network wherever that step still exists.
 */
export function setSpine(viewId, beats) {
  SPINES.set(viewId, beats.length ? beats : ENTRY_SPINE);
  if (viewId === state.view) setBeat(clampToSpine(state.beat));
}

/**
 * The distinct coarse units of a spine, in spine order.
 *
 * The coarse controls address units by ORDINAL -- "the third one" -- rather
 * than by the value in `beat.unit`, which is deliberate and load-bearing. The
 * instructor says "go back to the second one", and what makes that the second
 * one is its position in the story, not an integer a view ticket happened to
 * number from zero. Reading the value directly would silently mis-jump on a
 * ladder numbered from 1 (an interdiction budget *k* starts at 1, not 0) and
 * would skip whole digits on a Pareto spine whose detents leave gaps where
 * duplicate plans collapsed out. Both of those are spines #42-#44 are expected
 * to build, so the coupling is removed here rather than left as a rule three
 * later tickets have to remember.
 */
function unitValues(viewId = state.view) {
  return [...new Set(spine(viewId).map((beat) => beat.unit))];
}

/** How many coarse units the active view's spine has. */
export function unitCount(viewId = state.view) {
  return unitValues(viewId).length;
}

/**
 * Jump to the *n*th coarse unit's beat *a*, counting from zero, or decline if
 * the view has no such unit.
 *
 * Both coarse controls end here -- the arrows and the digits differ only in how
 * they name the unit they want. Declining rather than clamping is the shared
 * half: an out-of-range unit leaves the picture exactly where it was, whether it
 * was asked for by leaning on an arrow or by mistyping a digit.
 */
function setUnitAt(ordinal) {
  const values = unitValues();
  if (ordinal < 0 || ordinal >= values.length) return false;
  return setBeat(spine().findIndex((beat) => beat.unit === values[ordinal]));
}

/** Which coarse unit, by ordinal, the current beat sits in. */
function currentUnitOrdinal() {
  const beat = spine()[state.beat];
  return beat ? unitValues().indexOf(beat.unit) : -1;
}

/** The index of the first beat -- beat *a* -- of the unit at an ordinal. */
function firstBeatOfUnitAt(ordinal) {
  const values = unitValues();
  return spine().findIndex((beat) => beat.unit === values[ordinal]);
}

/**
 * Rebuild every derived field from the current beat.
 *
 * The whole of what makes a beat idempotent: the reset comes first, so what a
 * beat did NOT set is cleared rather than inherited from whatever was on screen
 * a keypress ago. The pin goes with it -- a click pins a lane hot until the next
 * beat or `R`, and "the next beat" is a promise only this function can keep.
 *
 * Called on every beat change, and also by the page after a dataset is built:
 * the marks were cleared along with the old theater's edge ids, and the current
 * beat is the only thing that knows what should be marked instead.
 *
 * **Layers are rebuilt, not preserved, and the order of the three sources is
 * the decision.** The view's entry table goes down first, because a view's
 * layer table is its entry state and not an invariant; the beat overrides it,
 * because beats drive layer state as the story advances; and the instructor's
 * own toggles go on top, because a hand on the pointer is the most recent
 * authority in the room.
 *
 * Rebuilding from those three every time is what keeps a beat idempotent
 * *including its layers* -- a leftover layer from the beat before would make
 * the picture depend on the route taken to it. But rebuilding from the entry
 * table ALONE would destroy the hand toggles on the very next keypress, and the
 * cross-day mashup they exist for -- Day 3's cut over Day 4's interdicted
 * network -- is the strongest moment in the unit. The spec spends that mashup
 * on `R` and on nothing else, so `R` is the only thing here that clears
 * `layerOverrides`.
 */
export function resolveBeat() {
  clearPin();
  for (const set of Object.values(state.marks)) set.clear();
  /* Day 1's node subsets and its two headline extras reset with everything
   * else. A beat that inherited the last beat's overdrawn hub would flag the
   * right hub stepping forwards and the wrong one stepping back, which is
   * exactly what the idempotence rule exists to make impossible. */
  for (const set of Object.values(state.nodes)) set.clear();
  state.dispatch.clear();
  state.detent = null;
  state.note = null;
  /* `T`'s labelled no-op belongs to the keypress that produced it. Left
   * standing, it would sit under a later beat saying something about that beat
   * instead -- the same failure the idempotence rule exists to make impossible,
   * one slot further down the panel. */
  state.threatNoOp = false;
  state.throughput = null;
  state.cut = null;
  state.tracks = null;
  state.search = null;
  state.sourceSide = null;
  state.delta = null;
  /* The trace slice goes with the rest. A beat that inherited the last beat's
   * flows would draw the right picture forwards and the wrong one backwards,
   * which is the exact failure the idempotence rule exists to make impossible. */
  state.flows.clear();
  state.residuals.clear();
  state.bottleneck = null;
  state.path = [];
  state.layers = layersForView(state.view);

  const beat = spine()[state.beat];
  if (beat && beat.apply) beat.apply(state);

  /* What the beat asked for, kept so a later hand toggle can be re-applied over
   * it without re-running the beat -- running `apply` again would clear the pin
   * and the marks, and a click on a lane must survive a click on a layer. */
  beatLayers = new Set(state.layers);
  state.layers = withOverrides(beatLayers);
}

/** The beat's own layer set, before the instructor's toggles go on top. */
let beatLayers = new Set();

/** A layer set with the hand toggles applied over it. */
function withOverrides(base) {
  const resolved = new Set(base);
  for (const [layerId, on] of state.layerOverrides) {
    if (on) resolved.add(layerId);
    else resolved.delete(layerId);
  }
  return resolved;
}

/**
 * Jump to a beat by index. Returns whether it happened.
 *
 * Out of range is a silent no-op rather than a clamp or a wrap: leaning on `->`
 * at the end of the ladder must not restart the story, and a mistyped digit
 * must not move the picture at all.
 */
export function setBeat(index) {
  if (index < 0 || index >= spine().length) return false;
  state.beat = index;
  resolveBeat();
  return true;
}

/** One beat forward (`+1`) or back (`-1`). */
export function stepBeat(delta) {
  return setBeat(state.beat + delta);
}

/**
 * One coarse unit forward (`+1`) or back (`-1`), landing on that unit's beat
 * *a*.
 *
 * Backward stepping exists at BOTH granularities rather than choosing between
 * them, because the interrupted instructor wants "iteration 3", not three
 * counted presses. Going back from mid-unit lands on the start of the unit
 * being interrupted, not the previous one -- the same as every other transport
 * control the instructor has ever used, and the reading that answers "start
 * this one again" without a wasted press.
 */
export function stepUnit(delta) {
  const ordinal = currentUnitOrdinal();
  if (ordinal === -1) return false;
  if (delta < 0 && state.beat !== firstBeatOfUnitAt(ordinal)) {
    return setUnitAt(ordinal);
  }
  return setUnitAt(ordinal + delta);
}

/**
 * Jump to a coarse unit by its 1-based number, as the digit keys name it.
 *
 * Digits above the view's unit count do nothing rather than wrapping or
 * clamping. A mistyped key is a no-op; a clamp would move the picture to
 * somewhere nobody asked for while the instructor is mid-sentence.
 */
export function jumpToUnit(number) {
  return setUnitAt(number - 1);
}

/**
 * `R`: a FULL reset of the current view -- beat 0, default layers, threat
 * cleared -- leaving the view and the dataset untouched.
 *
 * Full rather than partial on purpose: a half-reset that leaves four layers
 * burning is not a baseline, and the one key the instructor reaches for when
 * the picture has got away from them has to land somewhere known.
 *
 * THE ONLY THING THAT CLEARS THE HAND TOGGLES, which is where the accepted cost
 * bites: the cross-day layer mashup is both pointer-only *and* destroyed by
 * `R`. Every other control leaves it standing, which is what makes it usable at
 * all -- a mashup that did not survive a beat step could never be built while
 * the story was moving.
 */
export function resetView() {
  state.threat = null;
  /* The remembered picture goes with the live one, or `R` would not be the full
   * reset it advertises: the threat would come back on the next round trip
   * through `D`, from a stash the instructor has no control over.
   *
   * Note that the caller must re-apply the threat after this -- the spines on
   * screen were built from the old picture's payloads, and clearing the field
   * alone would leave the panel captioned pristine over a disrupted ladder. */
  state.threatByDataset.delete(state.dataset);
  state.beat = 0;
  state.layerOverrides.clear();
  resolveBeat();
}

/**
 * Switch view, restoring everything that view was last left holding.
 *
 * The beat index and the hand toggles are both remembered, which is the point:
 * Flow & Cut stays parked on augmentation 3 while the instructor detours to
 * answer a question. A view seen for the first time enters at beat 0 with its
 * default layers.
 *
 * Note what is remembered: the OVERRIDES, not the resolved layer set. The
 * resolved set is derived from the view table, the beat and the overrides, and
 * remembering a derived value is how a view comes back showing a layer state
 * that no longer follows from anything on screen.
 */
export function setView(viewId) {
  /* Pressing a view's own key is a no-op, not a re-entry. It has to be: the
   * stash below would otherwise write the current view's state and read it
   * straight back, which is harmless in the middle of a class and is exactly
   * how booting into the first view once left every layer switched off. */
  if (viewId === state.view) return;
  state.views[state.view] = {
    beat: state.beat,
    overrides: new Map(state.layerOverrides),
  };
  state.view = viewId;
  const remembered = state.views[viewId];
  state.beat = remembered ? clampToSpine(remembered.beat, viewId) : 0;
  state.layerOverrides = remembered ? new Map(remembered.overrides) : new Map();
  resolveBeat();
}

/**
 * Toggle one layer by hand, and remember that the hand did it.
 *
 * Recorded as an override rather than written straight onto `state.layers`,
 * because the layer set is rebuilt from scratch on every beat. Writing the set
 * directly would put the toggle on screen for exactly as long as it took to
 * press the next key.
 *
 * Re-resolves the layers alone, not the whole beat: a pinned lane must survive
 * a layer toggle, and the marks have not changed.
 */
export function toggleLayer(layerId) {
  state.layerOverrides.set(layerId, !state.layers.has(layerId));
  state.layers = withOverrides(beatLayers);
}

/** Switch threat picture. `null` restores the pristine network. */
export function setThreat(name) {
  state.threat = name;
}

/* ---- the two cycling axes (issue #45) -------------------------------------
 *
 * `D` and `T` move the dataset and the threat picture WITHOUT leaving the beat
 * the instructor is on, which is the whole of what they are for: park on a
 * detent, cycle the picture, and watch the same plan buckle -- or hold the same
 * step and change network. Neither of them may touch `state.beat`.
 *
 * Carrying the index across is a CLAMP and it is `setSpine`'s, not a second one
 * here. Every ladder in this application is derived from data, so a spine's
 * length moves under the instructor whenever either of these keys is pressed;
 * clamping on install is what keeps the render pure across that move, and an
 * assignment in either function below would restart the story on the key whose
 * entire purpose is not to.
 */

/** Every dataset id, in the order `/datasets` gave them. */
export function setDatasets(ids) {
  state.datasets = ids;
}

/** The names of the pictures this dataset declares, in payload order. */
export function threatNames(current = state) {
  return current.scenario ? Object.keys(current.scenario.threat_pictures) : [];
}

/**
 * The dataset `D` moves to, or `null` when there is nowhere to go.
 *
 * Wraps, unlike the beat ladder: the ends of a story must not join up, but a
 * set of theaters has no ends -- it is a ring the instructor walks round, and
 * "press it twice at two datasets and you are home" is the property that makes
 * the excursion cheap enough to take mid-sentence.
 */
export function nextDataset(current = state) {
  const at = current.datasets.indexOf(current.dataset);
  if (at === -1 || current.datasets.length < 2) return null;
  return current.datasets[(at + 1) % current.datasets.length];
}

/** Remember this dataset's threat picture before `D` leaves it. */
export function stashThreat() {
  if (state.dataset !== null) {
    state.threatByDataset.set(state.dataset, state.threat);
  }
}

/**
 * Take up the picture this dataset was last left on, if it still declares one.
 *
 * Called once the new `/scenario` payload is in hand and BEFORE anything is
 * fetched with it, because the threat is a parameter of all four solver
 * requests: restored afterwards, the spines on screen would be the pristine
 * network's under a panel captioned with a threat picture.
 */
export function restoreThreat() {
  const remembered = state.threatByDataset.get(state.dataset);
  state.threat = threatNames().includes(remembered) ? remembered : null;
}

/**
 * `T`: baseline -> each declared picture -> baseline. Returns whether it moved.
 *
 * It comes home to `null` rather than cycling the pictures alone, because the
 * pristine network is where the comparison is made FROM -- a cycle with no way
 * back would strand the instructor inside the theater.
 *
 * Declining is recorded rather than silent. See `threatNoOp`.
 */
export function cycleThreat() {
  const names = threatNames();
  state.threatNoOp = names.length === 0;
  if (state.threatNoOp) return false;
  /* `indexOf` answers -1 on the pristine network, which is exactly the position
   * before the first picture -- so baseline is the zeroth stop of the cycle
   * rather than a case tested for separately. */
  const at = names.indexOf(state.threat);
  state.threat = at + 1 < names.length ? names[at + 1] : null;
  return true;
}

/**
 * The nodes this threat picture has cut off entirely, as node ids.
 *
 * READ out of the server's `changes` block like everything else about a
 * disruption: a node is severed when every stored lane touching it has been
 * removed. That is one question asked through `isRemoved`, so a severed hub and
 * a struck lane cannot answer it differently -- and it catches a hub isolated
 * by removing its lanes one at a time just as it catches `remove_node`, which
 * reading the declarations would not.
 *
 * This exists because **removing a node leaves its quantity intact**. The hub
 * still reports its stock and the network still reports full total supply, so a
 * panel with nothing to say about it would sit there reading unchanged beside a
 * visibly severed hub -- inviting exactly the wrong question at the moment the
 * instructor is making the opposite point. The answer is a mark and a count in
 * the panel, never a mutated total: the figure is the server's.
 */
export function severedNodes(current, changes) {
  const severed = new Set();
  if (!current.scenario || !changes.size) return severed;
  const incident = new Map();
  for (const edge of current.scenario.network.edges) {
    for (const nodeId of [edge.src, edge.dst]) {
      if (!incident.has(nodeId)) incident.set(nodeId, []);
      incident.get(nodeId).push(edge.id);
    }
  }
  /* A node with no lanes at all never enters the map, which is right: it was
   * already isolated in the pristine network, and nothing was taken from it. */
  for (const [nodeId, lanes] of incident) {
    if (lanes.every((edgeId) => isRemoved(changes, edgeId))) severed.add(nodeId);
  }
  return severed;
}

/**
 * Pin one lane hot, or unpin it if it is already the pinned one.
 *
 * The rule a pointer action in the panel lives under: it may only duplicate an
 * existing keyboard jump, or produce transient emphasis that no later state
 * depends on. It may never reach a state the keyboard cannot. This is the
 * second kind -- the pin is emphasis and nothing reads it but the render pass,
 * so there is no sequence of clicks that puts the app somewhere `R` cannot
 * bring it back from.
 */
export function pinLane(edgeId) {
  state.pinned = state.pinned === edgeId ? null : edgeId;
}

/**
 * Drop the pin. Bound to `R`, and the beat engine (#41) must call this too:
 * the pin lasts until the next beat or `R`, and "the next beat" is a promise
 * only the beat mutator can keep.
 */
export function clearPin() {
  state.pinned = null;
}

/**
 * The post-disruption state of every stored edge under the active threat, keyed
 * by edge id -- or an empty map on the pristine network.
 *
 * A lookup into what the server already computed. This is the only place the
 * frontend learns that a lane's capacity changed, and it learns it by reading.
 */
export function edgeChanges(current = state) {
  const picture = current.threat
    && current.scenario
    && current.scenario.threat_pictures[current.threat];
  const changes = new Map();
  if (!picture) return changes;
  for (const change of picture.changes) changes.set(change.id, change);
  return changes;
}

/**
 * Whether a lane is removed, given the change map `edgeChanges` returned.
 *
 * Takes the map rather than fetching it, so a render pass over twelve lanes
 * builds it once instead of twelve times -- and, more to the point, so every
 * lane in one pass is judged against the same map.
 *
 * Removal is a style, not a deletion: the DOM is built from the pristine
 * network, so a cut lane keeps its element and gains a class. A lane that
 * vanishes teaches less than a lane visibly struck out -- and the server says
 * a lane is gone by zeroing its capacity, so that is what is read here.
 */
export function isRemoved(changes, edgeId) {
  const change = changes.get(edgeId);
  return Boolean(change) && change.cap === 0;
}

/* ---- the Flow & Cut spine (issue #42) -------------------------------------
 *
 * One `/maxflow?trace=true` payload in, one complete spine out. Pure: it reads
 * the payload and closes over it, and every `apply` below only ever *copies*
 * numbers the server computed onto the state object. There is no arithmetic
 * here and there must never be -- a residual or a flow derived in JavaScript is
 * a number on the projector the API can disagree with, discovered when it
 * contradicts an answer the same tool gave a minute earlier.
 *
 * The lane lookup is passed in rather than imported. `graph.js` owns it, but it
 * is frozen geometry rather than DOM, and taking it as an argument keeps this
 * module free of any dependency on the module that builds elements -- the same
 * import direction that keeps the render pass from appending.
 */

/**
 * Copy one trace step's residuals and per-edge flows onto the state.
 *
 * The uniform render rule this exists to serve: **residuals from step k-1,
 * path annotation from step k**. Which is why the server prepends a step 0 --
 * iteration 1 otherwise has no "before" to draw against, and synthesising one
 * here would be residual-graph construction in the browser.
 */
function showStep(current, step, laneOf) {
  for (const arc of step.flows) {
    const lane = laneOf(arc.src, arc.dst);
    /* Only the arc drawn in the lane's stored orientation sets the lane's flow.
     * A bidirectional lane is ONE stored edge and TWO solver arcs, so without
     * this the second arc would overwrite the first and which number survived
     * would depend on payload order. */
    if (lane && lane.stored) current.flows.set(lane.edgeId, arc.flow);
  }
  /* Both residual lists into one map: an arc is an arc, and what decides which
   * side of the lane it is drawn on is its direction, not which list the
   * solver filed it under. `null` is an unbounded terminal arc -- no numeral
   * and no mark, which is correct anyway. */
  for (const arc of [...step.forward_residual, ...step.reverse_residual]) {
    const lane = laneOf(arc.src, arc.dst);
    if (!lane || arc.residual === null) continue;
    const entry = current.residuals.get(lane.edgeId) || {};
    entry[lane.stored ? "along" : "counter"] = arc.residual;
    current.residuals.set(lane.edgeId, entry);
  }
}

/** Mark the lanes of one step's augmenting path, and which way each was walked. */
function showPath(current, step, laneOf) {
  current.path = step.path;
  current.bottleneck = step.bottleneck;
  for (let i = 0; i + 1 < step.path.length; i += 1) {
    const lane = laneOf(step.path[i], step.path[i + 1]);
    if (!lane) continue;      /* a terminal arc: on the path, but not a lane */
    current.marks.onPath.add(lane.edgeId);
    current.marks.hot.add(lane.edgeId);
    if (lane.against) current.marks.against.add(lane.edgeId);
  }
  /* `used_reverse` is deliberately not read here. It names the arcs the solver
   * walked backwards, and every one of them is an arc OF THIS PATH -- so it
   * heats nothing the loop above has not already heated. What drives the
   * promotion is `against`, which is a fact about the drawn lane's direction
   * rather than about the solver's bookkeeping, and that is the right question:
   * the mark exists so the instructor can say "here it uses a residual arc,
   * which is not a lane", which is a claim about the picture. */
}

/**
 * The lane that set this augmentation's bottleneck, named as the room hears it.
 *
 * The one thing `lane_residuals` is for: it carries ONE TERM PER ARC OF THE
 * PATH -- `lane_residuals.length === path.length - 1` -- so the `min(...)` that
 * produced the bottleneck can be anchored back to the lane it came from. That
 * alignment is the whole reason the server stopped filtering unbounded terms
 * out of the list; dropping them used to slide every term one place and made
 * this question unanswerable.
 *
 * Named by its endpoints rather than by its edge id, because "the bottleneck is
 * A to B" is the sentence, and `e04` is not.
 */
function bindingLane(step) {
  const at = step.lane_residuals.findIndex(
    (term) => term !== null && term === step.bottleneck,
  );
  return at === -1 ? null : `${step.path[at]}→${step.path[at + 1]}`;
}

/**
 * Draw the min cut: its capacity, the partition it defines and the lanes
 * certifying it -- all off ONE `/maxflow` response.
 *
 * Shared by both spines that show a cut, which is the point rather than a
 * convenience. Max-flow/min-cut says the capacity must equal the throughput,
 * and Day 4 draws Day 3's certificate underneath its own wreckage: two views
 * rendering the same certificate from two blocks of code is how the cut ends up
 * meaning one thing on Wednesday and another on Thursday. The ladder payload's
 * own `min_cut_capacity` is deliberately never the number displayed.
 *
 * `hot` is the one thing the two views differ on, and it is a question about
 * whose subject the cut is: on Flow & Cut the cut IS the beat, and on the
 * interdiction ladder it is the board the adversary is working against, where
 * the emphasis belongs to the blockade.
 */
function showCut(current, payload, laneOf, hot) {
  current.cut = payload.cut_capacity;
  current.sourceSide = new Set(payload.source_side);
  for (const lane of payload.cut_lanes) {
    const found = laneOf(lane.src, lane.dst);
    if (!found) continue;
    current.marks.inCut.add(found.edgeId);
    if (hot) current.marks.hot.add(found.edgeId);
  }
}

/** Switch a beat's layers, by id, over whatever the view's entry table gave. */
function setLayers(current, on, off) {
  for (const id of on) current.layers.add(id);
  for (const id of off) current.layers.delete(id);
}

/**
 * The Flow & Cut spine: beat 0, two beats per augmentation, and the cut.
 *
 * **The coarse unit is the augmentation**, which is what the instructor says
 * out loud -- "iteration 3", never "beat 6". So the textbook set's three
 * augmentations are three units, and the digit keys mean what the room hears.
 *
 * The pristine network and the cut are folded into the first and last units
 * rather than given units of their own. That is a deliberate cost: pressing
 * `1` lands on the pristine graph rather than on augmentation 1's path. It buys
 * the thing that matters more -- a digit key that names the augmentation it
 * names on the board -- and `1` landing at the start of the story is the
 * reading of "go back to the beginning" anyone would expect anyway.
 *
 * The cut is the LAST BEAT OF THE LAST UNIT and not a view of its own, which is
 * the whole reason Days 2 and 3 share a screen: the min cut is a certificate of
 * the flow just computed, and re-rendering it on a fresh screen severs the
 * argument the certificate is making.
 */
export function flowCutSpine(payload, laneOf) {
  const trace = payload.trace || [];
  if (!trace.length) return [];

  /* `iteration` 0 is the graph before the first push. Everything after it is an
   * augmentation, and the augmentations are the units. */
  const steps = trace.slice(1);
  const lastUnit = Math.max(steps.length, 1);
  const beats = [{
    unit: 1,
    phase: "pristine",
    label: "Pristine network",
    apply: (current) => {
      showStep(current, trace[0], laneOf);
      current.throughput = trace[0].total_after;
      setLayers(current, ["residual"], ["path", "cut"]);
    },
  }];

  steps.forEach((step, index) => {
    const unit = index + 1;
    const before = trace[index];        /* step k-1, by construction */
    const binding = bindingLane(step);

    /* beat a -- the proposal: the path and what it can carry. Residuals are
     * the ones the path was FOUND in, which is step k-1's; the path and its
     * bottleneck are step k's. Drawing both from step k would show the path
     * against the residual graph it had already consumed. */
    beats.push({
      unit,
      phase: "a",
      label: binding
        ? `Augmentation ${unit}: bottleneck ${step.bottleneck} at ${binding}`
        : `Augmentation ${unit}: bottleneck ${step.bottleneck}`,
      apply: (current) => {
        showStep(current, before, laneOf);
        showPath(current, step, laneOf);
        current.throughput = before.total_after;
        /* The A/B pair is deliberately left alone. It is ONE slot for the whole
         * page and its subject is the before/after of a threat picture, which
         * is a comparison of two states that are never simultaneously visible.
         * An augmentation is not that -- the "after" arrives one keypress later
         * and is then simply on screen -- so claiming the slot here would spend
         * the page's only A/B on a number the next beat shows anyway. The push
         * is a headline scalar instead. */
        setLayers(current, ["residual", "path"], ["cut"]);
      },
    });

    /* beat b -- the consequence: the same lanes, updated. The path comes off,
     * so what is left on screen is exactly what the push changed. */
    beats.push({
      unit,
      phase: "b",
      label: `Augmentation ${unit}: residual update, total ${step.total_after}`,
      apply: (current) => {
        showStep(current, step, laneOf);
        current.throughput = step.total_after;
        for (let i = 0; i + 1 < step.path.length; i += 1) {
          const lane = laneOf(step.path[i], step.path[i + 1]);
          if (lane) current.marks.hot.add(lane.edgeId);
        }
        setLayers(current, ["residual"], ["path", "cut"]);
      },
    });
  });

  /* The certificate, over the completed flow, on the same screen. */
  beats.push({
    unit: lastUnit,
    phase: "cut",
    label: `Min cut: capacity ${payload.cut_capacity}`,
    apply: (current) => {
      showStep(current, trace[trace.length - 1], laneOf);
      current.throughput = payload.max_throughput;
      /* Both off ONE response. Max-flow min-cut says these must be equal, and
       * two numbers that must be equal, fetched by two routes, are a
       * contradiction waiting for a projector. Hot, because on this beat the
       * cut is the subject rather than the backdrop. */
      showCut(current, payload, laneOf, true);
      setLayers(current, ["cut"], ["residual", "path"]);
    },
  });

  return beats;
}

/* ---- the Interdiction spine (issue #43) -----------------------------------
 *
 * Two payloads in, one complete spine out, and the second one is not optional:
 * the ladder says which lanes the adversary takes, and `/maxflow` says which
 * lanes certify the min cut. The cut is on screen from beat 0 so that a
 * budgeted adversary rediscovering it reads as RECOGNITION rather than as a
 * surprise reveal -- which is also the cross-day mashup the layer catalog is
 * global for, Day 3's certificate over Day 4's wreckage.
 *
 * Pure, like the Flow & Cut spine above, and under the same standing ban: every
 * number here is copied off a payload. Nothing about how long Day 4 is, which
 * rungs collapsed or which of them diverge is decided in this file -- those are
 * server facts with tests of their own, and a second implementation of the stop
 * rule in a render pass would disagree with the CLI on the one dataset nobody
 * checked.
 */

/**
 * A rung's budget, as the label names it -- `2`, or `2-3` where the server
 * collapsed two budgets onto one picture.
 *
 * The collapse is the server's and the range is READ rather than detected: a
 * rung is a picture, and the same picture under two labels is a slide the class
 * reads as progress that did not happen. No shipped dataset collapses a rung
 * today -- while throughput is positive each extra unit of budget strictly
 * improves both tracks -- so this is the guard reporting idle, and the label is
 * what would tell the room if it ever stopped being idle.
 */
function rungBudget(rung) {
  return rung.k_through > rung.k ? `${rung.k}-${rung.k_through}` : `${rung.k}`;
}

/** A blockade's lanes, named as the room hears them: `A→B`, in payload order. */
function blockadeNames(removed) {
  return removed.map((lane) => `${lane.src}→${lane.dst}`).join(", ");
}

/**
 * A blockade's lanes as edge ids, resolved once when the spine is BUILT.
 *
 * Resolved here rather than inside a beat's `apply` for the same reason
 * everything else in this application is prefetched: a failure at build time
 * happens while the page is loading, and a failure inside `apply` happens on
 * the keypress that reaches it.
 *
 * And it throws rather than skipping. Every lane an interdiction names is a
 * stored lane -- unlike a trace path, which legitimately walks terminal arcs
 * that have no lane and no edge id -- so a miss here is the payload and the
 * drawn network disagreeing about what this theater contains. Skipped, it would
 * drop the lane from the picture AND from the `Struck` count, which is read off
 * the row flags: a headline number quietly too small, with nothing raised
 * anywhere. A blank page during setup is recoverable; that is not.
 */
function blockadeIds(removed, laneOf) {
  return removed.map((lane) => {
    const found = laneOf(lane.src, lane.dst);
    if (!found) {
      throw new Error(
        `/interdict removed ${lane.src}→${lane.dst}, which this network has no `
        + `lane for -- the ladder and the drawn theater disagree`,
      );
    }
    return found.edgeId;
  });
}

/**
 * Heat a blockade's lanes, and strike them out if the blockade is drawn.
 *
 * Every blockade the ladder names is HOT -- it is what the beat is talking
 * about, whether it is greedy's guess on the live network or the optimum's
 * verdict. Only the drawn one is also `struck`, and only one is ever drawn.
 */
function markBlockade(current, edgeIds, drawn) {
  for (const edgeId of edgeIds) {
    current.marks.hot.add(edgeId);
    if (drawn) current.marks.struck.add(edgeId);
  }
}

/**
 * The Interdiction spine: the pristine cut, then two beats per budget level.
 *
 * **The coarse unit is the budget level *k***, which is what the instructor
 * says out loud -- "budget two", never "beat five" -- so the digit keys mean
 * what the room hears. The rungs' own `k` values are not read as ordinals
 * anywhere: `unitCount` and the digit keys address units by POSITION, which is
 * what lets a ladder numbered from 1, or one with a rung collapsed out of the
 * middle, still answer `2` with its second rung.
 *
 * The pristine network is folded into the first rung rather than given a unit
 * of its own, exactly as Flow & Cut folds its own opening beat in, and at the
 * same accepted cost: `1` lands on the untouched theater rather than on budget
 * 1's first blockade. It buys a digit key that names the budget it names on the
 * board.
 *
 * **Greedy's blockade first, then the optimum's** -- hypothesis, then verdict.
 * Greedy's pick is the one the room can predict from the board, because it is
 * just the biggest lane, so it is the guess the instructor invites them to make
 * out loud; reversing the order would put the answer on screen before the
 * question. It also leaves the rung's LAST beat holding the true residual, so
 * stepping to the next *k* departs from the correct picture rather than from
 * greedy's stall.
 *
 * Accepted costs, stated so they are not later read as bugs: a diverging rung
 * shows a wrong answer first and lives with it for both of its beats, the panel
 * never shows both blockades at once, and the spatial punchline -- greedy at
 * the source, the optimum at the sink -- becomes a comparison across a keypress.
 */
export function interdictionSpine(ladder, maxflow, laneOf) {
  const rungs = ladder.rungs || [];
  if (!rungs.length) return [];

  /* The certificate, on every beat of the ladder and never hot: the cut is the
   * board the adversary is working against, and the emphasis belongs to the
   * blockade. Shared with the Flow & Cut spine so the two views cannot render
   * the same certificate differently. */
  const cut = (current) => showCut(current, maxflow, laneOf, false);

  /* The untouched theater's throughput, off the SAME response as the cut
   * capacity it must equal.
   *
   * `ladder.baseline_throughput` is the same quantity and is deliberately not
   * the one displayed, for the reason `min_cut_capacity` is not either: on the
   * pristine beat this number and the cut sit one slot apart on the dashboard,
   * max-flow/min-cut says they must be equal, and two numbers that must be
   * equal, fetched by two routes, are a contradiction waiting for a projector.
   * The only ladder numbers that reach the screen are ones no other response
   * also computes -- the residuals, the counts and the divergence flag. */
  const baseline = maxflow.max_throughput;

  const beats = [{
    unit: rungs[0].k,
    phase: "pristine",
    label: `Pristine theater: min cut ${maxflow.cut_capacity}`,
    apply: (current) => {
      cut(current);
      current.throughput = baseline;
    },
  }];

  for (const rung of rungs) {
    /* Both tracks' residuals, on both beats of the rung. The pair is what makes
     * agreement a statement rather than an absence, and it stands through the
     * whole rung so that the guess and the verdict are read against each other
     * rather than one replacing the other. */
    const tracks = {
      greedy: rung.greedy.residual_throughput,
      optimum: rung.exhaustive.residual_throughput,
    };
    /* `diverges` is the server's flag, carried onto both of the rung's rows so
     * the timeline can say "k=1 agrees, k=2 and k=3 do not" without the ladder
     * being stepped. It compares the removed SETS rather than the residuals --
     * at k=3 on the trap both tracks read zero and the sets differ by a whole
     * lane, and a residual comparison would call that agreement and erase the
     * lesson. That comparison is the server's, and it stays there. */
    const diverges = rung.diverges;
    const budget = rungBudget(rung);
    /* Both blockades resolved to edge ids up front, so a lane the diagram
     * cannot draw fails while the page is loading rather than on the keypress
     * that reaches it. */
    const guess = blockadeIds(rung.greedy.removed, laneOf);
    const verdict = blockadeIds(rung.exhaustive.removed, laneOf);

    /* beat a -- the hypothesis: greedy's chosen lane set, on the LIVE network.
     * The lanes are hot rather than struck, and the throughput is still the
     * baseline: nothing has been taken away yet, and the room is being asked to
     * predict what happens when it is. */
    beats.push({
      unit: rung.k,
      phase: "a",
      diverges,
      label: `Budget ${budget}: greedy takes ${blockadeNames(rung.greedy.removed)}`,
      apply: (current) => {
        cut(current);
        current.throughput = baseline;
        current.tracks = tracks;
        current.search = {
          searched: rung.greedy.searched,
          skipped: rung.greedy.skipped,
        };
        markBlockade(current, guess, false);
      },
    });

    /* beat b -- the verdict: the optimum's blockade, removed, and what that
     * costs. The A/B pair is claimed here and this is the view it belongs to:
     * the two states are never simultaneously visible, "attacked" is carried by
     * the flip because THE TRANSITION IS THE VERB, and one pair the instructor
     * can say out loud beats a per-lane delta column nobody can. */
    beats.push({
      unit: rung.k,
      phase: "b",
      diverges,
      label: `Budget ${budget}: optimum removes `
        + `${blockadeNames(rung.exhaustive.removed)}, `
        + `throughput ${rung.exhaustive.residual_throughput}`,
      apply: (current) => {
        cut(current);
        current.throughput = rung.exhaustive.residual_throughput;
        current.tracks = tracks;
        current.search = {
          searched: rung.exhaustive.searched,
          skipped: rung.exhaustive.skipped,
        };
        markBlockade(current, verdict, true);
        current.delta = {
          label: "Throughput",
          before: baseline,
          after: rung.exhaustive.residual_throughput,
        };
      },
    });
  }

  /* A ladder that stopped at the budget ceiling rather than at a severed
   * network says so, on the last row the timeline shows. `terminated` is the
   * server's flag and this is the only thing the view does with it: untold, the
   * final rung reads as "and then the network was severed", which is the one
   * claim a truncated ladder cannot make. */
  if (!ladder.terminated) {
    const last = beats[beats.length - 1];
    last.label = `${last.label} — ladder truncated at the budget ceiling`;
  }

  return beats;
}

/* ---- the Cost & Risk spine (issue #44) ------------------------------------
 *
 * Two payloads in, one complete spine out, and the two are a MATCHED PAIR: the
 * server takes the same lambda list for both and answers in the same order, so
 * `sweep[i]` and `naive[i]` are the optimum and the collapse at one lambda and
 * the A/B flip is a swap at one index. Nothing here joins two lists.
 *
 * Pure and under the same standing ban as the other two spines: every number is
 * copied off a payload. In particular NO LOAD IS EVER COMPARED AGAINST A
 * CAPACITY HERE. `over` and `overage` are properties in the core and plain
 * fields on the wire precisely so a client can colour a lane from them, and a
 * second comparison in JavaScript is how a rounding difference puts a red lane
 * on the projector that the API does not agree is red.
 */

/**
 * The optimum's plan at one lambda, as an order-independent key.
 *
 * Sorted rather than taken in payload order, so "the same plan" is a fact about
 * the legs and not about how the solver happened to enumerate them.
 */
function legsKey(legs) {
  return legs
    .map((leg) => `${leg.src}>${leg.dst}:${leg.flow}`)
    .sort()
    .join("|");
}

/**
 * The naive plan at one lambda, as an order-independent key.
 *
 * The convoys alone, and that is sufficient rather than partial: the server
 * derives the lane loads and the hub dispatch totals FROM the convoys, so two
 * lambdas with the same convoys have the same violations by construction.
 * Keying the derived lists too would be the same question asked three times.
 */
function convoysKey(convoys) {
  return convoys
    .map((convoy) => `${convoy.dst}<${convoy.origin}:${convoy.quantity}:`
                     + `${convoy.found ? convoy.path.join(">") : "-"}`)
    .sort()
    .join("|");
}

/**
 * Every lambda row, each tagged with the Pareto detent it belongs to.
 *
 * **THE COARSE UNIT IS A DISTINCT PARETO POINT, NOT A LAMBDA VALUE.** The eight
 * default lambdas collapse to four distinct plans on the shipped theater, so
 * walking lambda positions would make the first four presses of Day 1 change
 * nothing on screen -- the exact dead-key failure the beat model exists to
 * prevent, sitting in the default sweep at the worst possible moment.
 *
 * **The dedup is on the PAIR, and a block collapses only if NEITHER side
 * moved.** Deduping on the optimum alone is the same bug one step later: the
 * theater has a lambda where the naive plan moves and the optimum does not, and
 * collapsing it would hide the ticket's own punchline -- that the naive plan
 * fails at every lambda and gets *worse*.
 *
 * ALL EIGHT ROWS COME BACK, tagged rather than filtered. The dedup only pays
 * for itself as a sentence -- "the frontier has four points, not eight; lambda
 * is a dial with detents" -- if the collapsed rows are still on screen to be
 * pointed at. `first` is what lets the panel draw them as duplicates and what
 * lets the spine below take one detent per block.
 *
 * ONE IMPLEMENTATION, two consumers -- the panel's rows and the spine's detents
 * are the same decision. It is *called* twice, once by `costRiskSpine` and once
 * by the page for the table, which is safe precisely because it is pure: same
 * payloads in, same tagging out. What must never happen is a second piece of
 * code deciding where a block ends, because then the row the panel marks and
 * the beat the keyboard reaches could disagree mid-sentence.
 */
export function paretoRows(sweep, naive) {
  const rows = [];
  let previous = null;
  let detent = 0;
  sweep.forEach((optimum, index) => {
    const collapse = naive[index];
    const key = `${legsKey(optimum.legs)}#${convoysKey(collapse.convoys)}`;
    const first = key !== previous;
    if (first) detent += 1;
    previous = key;
    rows.push({
      index,
      detent,
      first,
      lambda: optimum.risk_aversion,
      fill: optimum.fill_rate,
      cost: optimum.transit_cost,
      risk: optimum.risk_exposure,
      notional: collapse.notional_cost,
    });
  });
  return rows;
}

/**
 * A lane named by a directed pair, or a build-time failure.
 *
 * Resolved when the spine is BUILT rather than inside a beat's `apply`, for the
 * reason everything else in this application is prefetched: a failure at build
 * time happens while the page is loading, and a failure inside `apply` happens
 * on the keypress that reaches it, in front of a room.
 *
 * It throws rather than skipping. Every lane a plan names is a stored lane --
 * unlike a trace path, which legitimately walks terminal arcs that have no lane
 * -- so a miss here is the payload and the drawn network disagreeing about what
 * this theater contains. Skipped, it would drop the lane from the picture AND
 * from the `Over cap` count, which is read off the row flags: a headline number
 * quietly too small, with nothing raised anywhere.
 */
function laneAt(laneOf, src, dst) {
  const found = laneOf(src, dst);
  if (!found) {
    throw new Error(
      `the naive plan uses ${src}→${dst}, which this network has no lane for `
      + `-- the plan and the drawn theater disagree`,
    );
  }
  return found.edgeId;
}

/** The lanes one convoy's route walks, as edge ids. */
function convoyLanes(convoy, laneOf) {
  const lanes = [];
  for (let i = 0; i + 1 < convoy.path.length; i += 1) {
    lanes.push(laneAt(laneOf, convoy.path[i], convoy.path[i + 1]));
  }
  return lanes;
}

/**
 * A detent's lambda block, listed rather than ranged -- `10`, or `0, 1, 2, 5`.
 *
 * Listed because the sweep is eight sampled values and not an interval: written
 * `0-5` the block would claim lambda 3 and lambda 4 collapsed into it too, and
 * neither was ever computed. The detent is the set of lambdas actually tried
 * that landed on this plan, and saying exactly which is the honest form of the
 * sentence the dedup exists for.
 */
function detentLambdas(rows, detent) {
  return rows
    .filter((row) => row.detent === detent)
    .map((row) => row.lambda)
    .join(", ");
}

/**
 * The Cost & Risk spine: two beats per Pareto detent.
 *
 * **Beat *a* is the naive plan with its violations; beat *b* is the flip to the
 * feasible optimum, with the delta in the headline.** Proposal then
 * consequence, like every other spine in this application, and here the
 * proposal is the plan the room itself proposes out loud: serve each
 * destination from its own cheapest hub. Beat *b* is the answer, and the flip
 * is the verb -- the two states are never simultaneously visible, which is what
 * makes one A/B pair the right shape and a per-lane delta column the wrong one.
 *
 * The two failures stay two things. An over-capacity lane is a mark on the LANE
 * and an over-stock hub is a mark on the NODE, so the room reads an *assignment*
 * error rather than merely a too-small pipe -- and every supply node renders,
 * idle healthy ones included, because an overdrawn hub beside a hub with spare
 * stock makes the allocation argument by itself.
 *
 * `network` is the pristine drawn network, and it is here for one question
 * only: whether this dataset carries any risk at all. See the note on the
 * degenerate combination below.
 */
export function costRiskSpine(sweep, naive, laneOf, network) {
  const rows = paretoRows(sweep, naive);
  if (!rows.length) return [];

  /* The degenerate view x dataset combination, LABELLED RATHER THAN STRUCK.
   *
   * On the textbook set every cost is 1 and no lane carries a risk key, so
   * lambda multiplies zero and all eight lambdas return one identical plan: a
   * one-beat ladder with Day 1's punchline mute. Striking the combination was
   * rejected because view-aware behaviour is exactly the hidden modality the
   * key assignments were designed to avoid, and authoring risk into that file
   * was rejected because it invents meaningless numbers the room will ask
   * about, in a dataset tuned for a completely different property.
   *
   * So the headline says it instead. Both halves are required: a single-point
   * frontier with real risk data is a fact about that theater and not a
   * shortcoming to apologise for, and risk-free data that still moved would
   * make the sentence false. */
  const noRisk = network.edges.every((edge) => edge.risk === 0);
  const singlePoint = rows[rows.length - 1].detent === 1;
  const note = noRisk && singlePoint
    ? "no risk data; frontier is a single point"
    : null;

  const beats = [];
  for (const row of rows) {
    /* A collapsed lambda is not a second detent. It keeps its panel row -- see
     * `paretoRows` -- but it gets no beats, which is the whole point: the
     * keyboard's coarse unit is the Pareto point the instructor names out loud,
     * and four of the eight presses would otherwise change nothing. */
    if (!row.first) continue;

    const optimum = sweep[row.index];
    const collapse = naive[row.index];
    const budget = detentLambdas(rows, row.detent);

    /* Everything resolved to edge ids and node ids up front, so a lane the
     * diagram cannot draw fails while the page is loading rather than on the
     * keypress that reaches it. */
    const loads = collapse.lanes.map((lane) => ({
      edgeId: laneAt(laneOf, lane.src, lane.dst),
      load: lane.load,
      /* READ, never derived. The server already decided this. */
      over: lane.over,
    }));
    const overLanes = new Set();
    for (const lane of loads) if (lane.over) overLanes.add(lane.edgeId);

    /* Every supply node, with its readout, and separately the ones the plan
     * overdraws. A loop rather than a filter because both lists come out of the
     * one pass: the healthy hubs are half of Day 1's argument and must not be
     * filtered away on the route to finding the sick one. */
    const dispatch = [];
    const overdrawn = [];
    for (const source of collapse.sources) {
      dispatch.push([source.id, { dispatched: source.dispatched, stock: source.stock }]);
      if (source.over) overdrawn.push(source.id);
    }
    const overHubs = new Set(overdrawn);

    /* The two demand-node failures, which are different lessons and must not
     * render as one. `found: false` is a convoy that FAILED rather than a
     * missing row -- the convoy count equals the demand-node count either way,
     * which is why this frontend never reconciles two lists -- and it means
     * nothing reaches that base at all. An illegally-served base is the other
     * thing: it is in the plan, and the plan cheats to get there.
     *
     * The illegal test is a set-membership join over flags the server already
     * decided, never a recomputation of them. No shipped dataset has an
     * unreachable base today, so that branch is the guard reporting idle -- and
     * it is what would tell the room if that ever stopped being true. */
    const routeLanes = [];
    const unreachable = [];
    const illegal = [];
    for (const convoy of collapse.convoys) {
      if (!convoy.found) {
        unreachable.push(convoy.dst);
        continue;
      }
      const walked = convoyLanes(convoy, laneOf);
      for (const edgeId of walked) routeLanes.push(edgeId);
      if (overHubs.has(convoy.origin) || walked.some((id) => overLanes.has(id))) {
        illegal.push(convoy.dst);
      }
    }

    const legs = optimum.legs.map((leg) => ({
      edgeId: laneAt(laneOf, leg.src, leg.dst),
      flow: leg.flow,
    }));

    /* beat a -- the proposal: the plan the room proposes out loud, superimposed
     * and failing. The lane numerals are LOADS rather than flows, which is the
     * claim: this is what the convoys ask of each lane, and the ledger's own
     * capacity column beside it is what makes an over-subscribed lane visibly
     * over-subscribed. */
    beats.push({
      unit: row.detent,
      phase: "a",
      label: `Detent ${row.detent} (λ ${budget}): naive plan — `
        + `${overLanes.size} lane(s) over capacity, ${overdrawn.length} hub(s) `
        + `over stock`,
      apply: (current) => {
        current.detent = row.detent;
        current.note = note;
        for (const lane of loads) {
          current.flows.set(lane.edgeId, lane.load);
          current.marks.hot.add(lane.edgeId);
          if (lane.over) current.marks.violating.add(lane.edgeId);
        }
        for (const edgeId of routeLanes) current.marks.onPath.add(edgeId);
        for (const [id, pair] of dispatch) current.dispatch.set(id, pair);
        for (const id of overdrawn) current.nodes.overdrawn.add(id);
        for (const id of unreachable) current.nodes.unreachable.add(id);
        for (const id of illegal) current.nodes.illegal.add(id);
        /* CAPACITY, not cost and risk, on the beat that compares a load
         * against a capacity. The two share the anchor's lower row and overlap
         * if both are on -- which is why the catalog splits them at all -- so
         * the beat has to choose, and on beat *a* the sentence is "this lane is
         * asked for 90 and holds 60". Cost and risk are what explains why the
         * convoys chose these routes; they come back on the flip, where the
         * frontier's trade-off is the subject.
         *
         * This is a beat overriding the view's entry table, which is exactly
         * what `views.js` says an entry table is for: a view's layers are where
         * it opens, not an invariant it holds for every beat. */
        setLayers(current, ["naive", "route", "caps", "flow"],
                  ["costrisk", "residual", "path", "cut"]);
      },
    });

    /* beat b -- the consequence: the feasible optimum, and what it costs.
     *
     * The violations come off with the plan that caused them, and the naive and
     * route layers go with them: what is left on screen is a plan that can
     * actually be executed. The A/B pair is claimed here and this is the view it
     * belongs to -- the illegal plan looks cheaper precisely because it is
     * buying capacity that does not exist, and that is one number the instructor
     * can say out loud rather than twelve nobody can. */
    beats.push({
      unit: row.detent,
      phase: "b",
      /* Risk is written to two places, as it is everywhere else on this page.
       * It is a sum of quantities times per-lane risks, so it arrives with
       * binary-fraction noise -- `47.699999999999996` -- where cost, a sum of
       * quantities times whole costs, does not. Rounding for display is not
       * derivation: the number is still the server's, and this only decides how
       * many of its digits the back of the room is asked to read. */
      label: `Detent ${row.detent} (λ ${budget}): feasible optimum, `
        + `cost ${optimum.transit_cost}, risk ${optimum.risk_exposure.toFixed(2)}`,
      apply: (current) => {
        current.detent = row.detent;
        current.note = note;
        for (const leg of legs) {
          current.flows.set(leg.edgeId, leg.flow);
          current.marks.hot.add(leg.edgeId);
        }
        current.delta = {
          label: "Cost",
          before: collapse.notional_cost,
          after: optimum.transit_cost,
        };
        /* Cost and risk come back for the flip: the optimum's subject is what
         * the plan buys and what it exposes, which is the frontier this whole
         * view walks. Capacity goes off with the violation it was there to be
         * compared against. */
        setLayers(current, ["costrisk", "flow"],
                  ["naive", "route", "caps", "residual", "path", "cut"]);
      },
    });
  }

  return beats;
}

/**
 * The three node states, and the only list of them in the application code.
 *
 * The node-side twin of `ROW_STATES`, and a separate list rather than three
 * more members of that one because that separation IS the second violation's
 * structure: a lane subset says a pipe is too small and a node subset says an
 * assignment is wrong, and merging them would leave the room with two shades of
 * one failure. `render.js` iterates this array to toggle the classes, so a
 * fourth state is one edit here plus its stylesheet rule.
 */
export const NODE_STATES = ["overdrawn", "unreachable", "illegal"];

/**
 * Every state one node is in right now, as flags -- the node-side twin of
 * `laneStates`.
 *
 * One call, two consumers: the node's classes and the headline's `Over stock`
 * count. Because the render pass counts these flags and classes the node from
 * the same call, a headline number that disagreed with its nodes would have to
 * disagree with itself.
 *
 * The three are mutually exclusive in practice -- `overdrawn` is a supply node
 * and the other two are demand nodes -- but they are returned as independent
 * flags rather than as one role, because nothing here should depend on that
 * staying true of a dataset nobody has authored yet.
 */
export function nodeStates(current, nodeId) {
  return {
    overdrawn: current.nodes.overdrawn.has(nodeId),
    unreachable: current.nodes.unreachable.has(nodeId),
    illegal: current.nodes.illegal.has(nodeId),
  };
}

/**
 * The five row states, and the only list of them in the application code.
 *
 * `laneStates` below returns exactly these keys and `render.js` iterates this
 * array to toggle the classes, so a sixth state is one edit here plus its
 * stylesheet rule. (`tests/test_web_assets.py` states the list again on
 * purpose -- a test that imported the list under review could not catch it
 * losing a member.)
 */
export const ROW_STATES = ["removed", "in-cut", "violating", "on-path", "hot"];

/**
 * Whether ANYTHING is hot right now -- the single question the scaffold tier
 * turns on.
 *
 * **An empty hot set means every lane is hot**, which is what makes dimming
 * safe: the pristine network, the one picture whose subject is the graph
 * itself, is never dimmed. Read the rule as "there is nothing more specific to
 * look at, so look at all of it" rather than as a special case bolted on to
 * avoid an ugly screen.
 *
 * Exported so the canvas and the ledger cannot answer it differently. It is a
 * question about the whole state, not about a lane, which is why it does not
 * live inside `laneStates` below.
 */
export function anyHot(current = state) {
  return current.marks.hot.size > 0 || current.pinned !== null;
}

/**
 * Every state one lane is in right now, as flags -- the one projection of the
 * lane subsets onto a single lane.
 *
 * The single source is the point. Cut capacity, the interdicted count and the
 * violation count are headline numbers whose *certificates* are the row
 * classes, so the number and the lanes that justify it must never be two
 * separate renderings. Because the render pass counts these flags and classes
 * the row from the same call, a headline number that disagreed with its rows
 * would have to disagree with itself.
 *
 * `hot` is the emphasis channel rather than a fifth role: the beat's own hot
 * set, plus whatever the instructor pinned by clicking.
 *
 * `cold` is the sixth flag and deliberately NOT one of `ROW_STATES`: it is the
 * scaffold tier's question, answered per lane for the canvas, and it has no
 * ledger tick. Marking every cold row would ink eight of twelve rows on a
 * typical beat to say "not this one", where the hot tick already says which one
 * -- the same information, twice, in the noisier direction.
 *
 * Note that `hot` and `cold` are not complements. When nothing is hot, nothing
 * is cold either: no lane is emphasised and no lane is dimmed, which is the
 * pristine screen.
 */
export function laneStates(current, changes, edgeId) {
  const emphasised = current.marks.hot.has(edgeId) || current.pinned === edgeId;
  return {
    /* Two sources, one state. A threat picture removes a lane by zeroing its
     * capacity in `changes`; an interdiction removes it by naming it in the
     * ladder payload. Both are the server saying the lane is gone, and on
     * screen "gone" is one thing -- struck out, greyed, `X` -- so it is one
     * flag and one class rather than two that would have to agree. */
    "removed": isRemoved(changes, edgeId) || current.marks.struck.has(edgeId),
    "in-cut": current.marks.inCut.has(edgeId),
    "violating": current.marks.violating.has(edgeId),
    "on-path": current.marks.onPath.has(edgeId),
    "hot": emphasised,
    "cold": anyHot(current) && !emphasised,
  };
}
