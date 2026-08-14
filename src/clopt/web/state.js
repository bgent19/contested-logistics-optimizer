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

import { layersForView } from "./views.js";

export const state = {
  /** Dataset id currently drawn; `null` until the first load. */
  dataset: null,
  /** The `/scenario` payload, verbatim. */
  scenario: null,
  /** Active view id. */
  view: "theater",
  /** Active layer ids. */
  layers: new Set(),
  /** Active threat picture name, or `null` for the pristine network. */
  threat: null,

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

/** Switch view, adopting that view's default layer set. */
export function setView(viewId) {
  state.view = viewId;
  state.layers = layersForView(viewId);
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
 */
export function laneStates(current, changes, edgeId) {
  return {
    "removed": isRemoved(changes, edgeId),
    "in-cut": current.marks.inCut.has(edgeId),
    "violating": current.marks.violating.has(edgeId),
    "on-path": current.marks.onPath.has(edgeId),
    "hot": current.marks.hot.has(edgeId) || current.pinned === edgeId,
  };
}
