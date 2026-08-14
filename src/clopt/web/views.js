/* The three views, as sets of layer toggles -- and the layer catalog itself.
 *
 * A view is not a mode with behaviour. It is a named set of layers, and
 * switching to it is a set of class names on the root element. That is the
 * whole of it: no view owns a code path, so a view cannot drift from what the
 * same layers show when switched on by hand.
 *
 * The layers whose marks land in later tickets are listed here from the start.
 * The catalog is what the unit teaches from, and a layer that appears the day
 * its marks do is a layer whose toggle nobody has ever pressed before the
 * class it matters in.
 */

/** The layer catalog. `id` is the toggle; the root class is `show-<id>`. */
export const LAYERS = [
  { id: "lanelabels", label: "Lane labels", hint: "Capacity, cost and risk at each lane anchor" },
  { id: "flow",       label: "Flow",        hint: "Flow on each lane (Days 1-3)" },
  { id: "synth",      label: "S / T",       hint: "The derived super-source and super-sink" },
  { id: "residual",   label: "Residual",    hint: "Residual and reverse arcs (Day 2)" },
  { id: "path",       label: "Path",        hint: "Augmenting path and its bottleneck (Day 2)" },
  { id: "cut",        label: "Min cut",     hint: "The cut, and the S/T partition it defines (Day 3)" },
  { id: "removed",    label: "Interdicted", hint: "Lanes struck out by an interdiction (Day 4)" },
  { id: "naive",      label: "Naive load",  hint: "Day 1's counterexample and its violations" },
];

const LAYER_IDS = LAYERS.map((layer) => layer.id);

/**
 * The three views of the unit, each a default layer set.
 *
 * The pristine opening screen is the first entry's business: it switches on the
 * lanes' own labels and nothing else, so the theater opens as a bare node-link
 * diagram with zero marks over it.
 */
export const VIEWS = [
  {
    id: "theater",
    label: "Theater",
    hint: "The pristine network, as authored",
    layers: ["lanelabels", "synth"],
  },
  {
    id: "throughput",
    label: "Throughput",
    hint: "Max flow, residuals and the min cut (Days 2-3)",
    layers: ["flow", "synth", "residual", "path", "cut"],
  },
  {
    id: "interdiction",
    label: "Interdiction",
    hint: "What a budget of removals costs the theater (Day 4)",
    layers: ["flow", "synth", "cut", "removed"],
  },
];

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
