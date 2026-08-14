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
};

export function setScenario(payload) {
  state.scenario = payload;
}

export function setDataset(datasetId) {
  state.dataset = datasetId;
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
 * Whether a lane is removed under the active threat.
 *
 * Removal is a style, not a deletion: the DOM is built from the pristine
 * network, so a cut lane keeps its element and gains a class. A lane that
 * vanishes teaches less than a lane visibly struck out -- and the server says
 * a lane is gone by zeroing its capacity, so that is what is read here.
 */
export function isRemoved(edgeId, current = state) {
  const change = edgeChanges(current).get(edgeId);
  return Boolean(change) && change.cap === 0;
}
