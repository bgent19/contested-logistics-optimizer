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
   * Filled by the view tickets (#42-#44). `removed` is deliberately absent:
   * it is not a set anybody assigns, it is read out of the server's `changes`
   * block by `isRemoved`. */
  marks: {
    onPath: new Set(),     /* the augmenting path of the current beat */
    inCut: new Set(),      /* the lanes certifying the min cut */
    violating: new Set(),  /* lanes the naive plan overloads */
    hot: new Set(),        /* whatever the current beat is talking about */
    /* Lanes this beat's path traverses AGAINST their own direction -- the
     * reverse-arc moment. Not a sixth row state: it is a modifier on `on-path`
     * and never appears without it, which is what keeps a forward traversal
     * unmarked. It drives two things from one set, so the ledger's glyph and
     * the canvas's promoted arc can never disagree about which way a lane was
     * walked. */
    against: new Set(),
  },

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
  state.throughput = null;
  state.cut = null;
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
       * contradiction waiting for a projector. */
      current.cut = payload.cut_capacity;
      current.sourceSide = new Set(payload.source_side);
      for (const lane of payload.cut_lanes) {
        const found = laneOf(lane.src, lane.dst);
        if (found) {
          current.marks.inCut.add(found.edgeId);
          current.marks.hot.add(found.edgeId);
        }
      }
      setLayers(current, ["cut"], ["residual", "path"]);
    },
  });

  return beats;
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
    "removed": isRemoved(changes, edgeId),
    "in-cut": current.marks.inCut.has(edgeId),
    "violating": current.marks.violating.has(edgeId),
    "on-path": current.marks.onPath.has(edgeId),
    "hot": emphasised,
    "cold": anyHot(current) && !emphasised,
  };
}
