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
   * on a diagram with nothing drawn over it and no beat responsible for that. */
  layers: layersForView(VIEWS[0].id),
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
   * Per-view memory, `{viewId: {beat, layers}}`.
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
  },

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
 * Install a view's whole spine, prefetched and complete.
 *
 * Clamps rather than resets the beat index, so re-installing a spine -- which
 * is what a dataset switch does -- lands the instructor on the same step of the
 * other network wherever that step still exists.
 */
export function setSpine(viewId, beats) {
  SPINES.set(viewId, beats.length ? beats : ENTRY_SPINE);
  if (viewId === state.view) setBeat(Math.min(state.beat, spine().length - 1));
}

/** How many coarse units the active view's spine has. */
export function unitCount(viewId = state.view) {
  return new Set(spine(viewId).map((beat) => beat.unit)).size;
}

/** The index of the first beat -- beat *a* -- of a coarse unit. */
function firstBeatOfUnit(unit) {
  return spine().findIndex((beat) => beat.unit === unit);
}

/**
 * Rebuild every derived field from the current beat.
 *
 * The whole of what makes a beat idempotent: the reset comes first, so what a
 * beat did NOT set is cleared rather than inherited from whatever was on screen
 * a keypress ago. The pin goes with it -- a click pins a lane hot until the next
 * beat or `R`, and "the next beat" is a promise only this function can keep.
 *
 * Layers are reset to the view's defaults here too, because a view's layer
 * table is its *entry* state and beats drive it from there. The cost, stated:
 * a layer the instructor toggled by hand does not survive the next keypress.
 * That is the same rule read from the other end -- a beat renders identically
 * however it was reached, including "reached after fiddling with the layers".
 *
 * `seed` is the one exception, and it exists for exactly one caller: returning
 * to a view restores the layer set it was left holding, and the beat's own
 * overrides are then re-applied on top of that rather than in place of it.
 */
export function resolveBeat(seed) {
  clearPin();
  for (const set of Object.values(state.marks)) set.clear();
  state.throughput = null;
  state.cut = null;
  state.delta = null;
  state.layers = seed ? new Set(seed) : layersForView(state.view);

  const beat = spine()[state.beat];
  if (beat && beat.apply) beat.apply(state);
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
  const beats = spine();
  const current = beats[state.beat];
  if (!current) return false;
  if (delta < 0 && state.beat !== firstBeatOfUnit(current.unit)) {
    return setBeat(firstBeatOfUnit(current.unit));
  }
  const target = firstBeatOfUnit(current.unit + delta);
  return target === -1 ? false : setBeat(target);
}

/**
 * Jump to a coarse unit by its 1-based number, as the digit keys name it.
 *
 * Digits above the view's unit count do nothing rather than wrapping or
 * clamping. A mistyped key is a no-op; a clamp would move the picture to
 * somewhere nobody asked for while the instructor is mid-sentence.
 */
export function jumpToUnit(number) {
  const target = firstBeatOfUnit(number - 1);
  return target === -1 ? false : setBeat(target);
}

/**
 * `R`: a FULL reset of the current view -- beat 0, default layers, threat
 * cleared -- leaving the view and the dataset untouched.
 *
 * Full rather than partial on purpose: a half-reset that leaves four layers
 * burning is not a baseline, and the one key the instructor reaches for when
 * the picture has got away from them has to land somewhere known. Accepted
 * cost, stated where it bites: the cross-day layer mashup is both pointer-only
 * *and* destroyed by `R`.
 */
export function resetView() {
  state.threat = null;
  state.beat = 0;
  resolveBeat();
}

/**
 * Switch view, restoring everything that view was last left holding.
 *
 * The beat index and the layer set are both remembered, which is the point:
 * Flow & Cut stays parked on augmentation 3 while the instructor detours to
 * answer a question. A view seen for the first time enters at beat 0 with its
 * default layers.
 */
export function setView(viewId) {
  /* Pressing a view's own key is a no-op, not a re-entry. It has to be: the
   * stash below would otherwise write the current view's state and read it
   * straight back, which is harmless in the middle of a class and is exactly
   * how booting into the first view once left every layer switched off. */
  if (viewId === state.view) return;
  state.views[state.view] = { beat: state.beat, layers: new Set(state.layers) };
  state.view = viewId;
  const remembered = state.views[viewId];
  state.beat = remembered ? Math.min(remembered.beat, spine(viewId).length - 1) : 0;
  /* The marks and the headline numbers are rebuilt from the beat rather than
   * remembered alongside it -- they are derived, and storing derived state is
   * how a remembered view comes back showing last week's numbers. Layers are
   * the exception because a hand toggle is not derivable from anything, so
   * they are seeded back in and the beat's overrides re-applied over them. */
  resolveBeat(remembered && remembered.layers);
}

export function toggleLayer(layerId) {
  if (state.layers.has(layerId)) state.layers.delete(layerId);
  else state.layers.add(layerId);
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
