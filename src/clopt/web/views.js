/* The three views, as sets of layer toggles -- and the layer catalog itself.
 *
 * A view is not a mode with behaviour. It is a named set of layers, and
 * switching to it is a set of class names on the root element. That is the
 * whole of it: no view owns a code path, so a view cannot drift from what the
 * same layers show when switched on by hand.
 *
 * **One global catalog; a view is a named default toggle-state, not an owner.**
 * View-scoping was rejected because the unit's strongest moments are cross-day
 * mashups -- showing Day 3's cut on top of Day 4's interdicted network is Day
 * 4's entire punchline, and a layer owned by a view cannot be borrowed by
 * another one.
 *
 * **A view's layer table is its ENTRY state only, not an invariant.** Beats
 * drive layer state from there, so a view can change what is shown as its story
 * advances without any of that living in a view-shaped code path.
 *
 * The layers whose marks land in later tickets are listed here from the start.
 * The catalog is what the unit teaches from, and a layer that appears the day
 * its marks do is a layer whose toggle nobody has ever pressed before the
 * class it matters in.
 */

/** The layer catalog. `id` is the toggle; the root class is `show-<id>`. */
export const LAYERS = [
  /* Base topology is on in all three views. It is still a toggle rather than a
   * permanent fixture, because taking the derived S/T machinery away while
   * talking about the authored network alone is a thing the instructor asks
   * for -- and a mark that can never be switched off is one nobody can check
   * the graph against. */
  { id: "synth",    label: "S / T",      hint: "The derived super-source and super-sink" },
  /* Two layers where there was one text. Flow & Cut wants capacities beside a
   * flow; Cost & Risk wants cost and risk instead. A single `cap/cost/risk`
   * label put two unasked-for numbers on screen in both. */
  { id: "caps",     label: "Capacity",   hint: "Capacity at each lane anchor (Days 2-4)" },
  { id: "costrisk", label: "Cost / risk", hint: "Cost and risk at each lane anchor (Day 1)" },
  { id: "flow",     label: "Flow",       hint: "Flow on each lane (all three views)" },
  { id: "residual", label: "Residual",   hint: "Residual and reverse arcs (Day 2)" },
  { id: "path",     label: "Path",       hint: "Augmenting path and its bottleneck (Day 2)" },
  { id: "cut",      label: "Min cut",    hint: "The cut, and the S/T partition it defines (Day 3)" },
  { id: "removed",  label: "Interdicted", hint: "Lanes struck out by an interdiction (Day 4)" },
  { id: "route",    label: "Single path", hint: "The cheapest or safest single route (Day 1)" },
  { id: "naive",    label: "Naive load", hint: "Day 1's counterexample and its violations" },
];

const LAYER_IDS = LAYERS.map((layer) => layer.id);

/**
 * The three views of the unit, in DAY ORDER, which is also left-to-right on the
 * keyboard: `Z` `X` `C`.
 *
 * The keys are declared here rather than in the page's key map so that day
 * order has one home. Bottom-row, one-handed, no modifier -- function keys were
 * rejected because the function row defaults to media keys on many laptops and
 * needs a modifier, which is a live-class hazard on the most-pressed non-beat
 * key.
 *
 * Each view's `layers` is its entry state. Note that no view lists the whole
 * catalog and none may: `WORST CASE` -- every layer on at once -- is illegible
 * in every colour scheme, so all-on is not a legal preset and there is no
 * control that produces it. `tests/test_web_assets.py` asserts it rather than
 * leaving it as a thing everyone agrees about.
 */
export const VIEWS = [
  {
    /* Day 1: routing is the wrong model, and the lambda/Pareto sequel. The
     * naive plan and its violations are the subject, so the lane numerals here
     * are cost and risk -- capacity is what the *next* view is about. */
    id: "cost-risk",
    key: "KeyZ",
    label: "Cost & Risk",
    hint: "Day 1: why serving each base from its cheapest hub fails",
    layers: ["synth", "costrisk", "flow", "route", "naive"],
  },
  {
    /* Days 2-3, merged: the min cut is a certificate OF the flow just computed,
     * and re-rendering it on a fresh screen severs the argument. */
    id: "flow-cut",
    key: "KeyX",
    label: "Flow & Cut",
    hint: "Days 2-3: Edmonds-Karp, and the cut that certifies it",
    layers: ["synth", "caps", "flow", "residual", "path", "cut"],
  },
  {
    /* Day 4 stands alone: it is the adversary's turn, a different actor. The
     * cut is on from beat 0 so that a budgeted adversary rediscovering it reads
     * as recognition rather than as a surprise reveal. */
    id: "interdiction",
    key: "KeyC",
    label: "Interdiction",
    hint: "Day 4: what a budget of removals costs the theater",
    layers: ["synth", "caps", "flow", "cut", "removed"],
  },
];

/** The view a key code selects, or `null`. */
export function viewForKey(code) {
  const view = VIEWS.find((candidate) => candidate.key === code);
  return view ? view.id : null;
}

/** A view's default layer set, as a fresh `Set` the caller may mutate. */
export function layersForView(viewId) {
  const view = VIEWS.find((candidate) => candidate.id === viewId);
  return new Set(view ? view.layers : []);
}

/**
 * Project the active layer set onto the root element's class list.
 *
 * Every layer's class is written every time -- added or removed -- rather than
 * only the ones that changed. Layer visibility is the one piece of app state
 * that lives outside the state object, in the DOM, and reconciling the whole
 * set each pass is what stops the two drifting.
 */
export function applyLayerClasses(root, active) {
  for (const id of LAYER_IDS) {
    root.classList.toggle(`show-${id}`, active.has(id));
  }
}
