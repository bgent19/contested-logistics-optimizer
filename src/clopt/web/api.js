/* Every fetch, and the only module that knows an endpoint URL.
 *
 * Confining the URLs here keeps the blast radius of every API contract decision
 * to one file: when an endpoint gains a parameter or changes shape, exactly one
 * module needs reading. `tests/test_web_assets.py` asserts that no other module
 * contains an endpoint path, so the rule is enforced rather than merely agreed.
 *
 * Paths are relative, and that is load-bearing: the page is served from the same
 * origin as the API by `clopt.api`, so there is no host to configure and nothing
 * to point at a machine that will not be on the classroom network.
 */

const ENDPOINTS = {
  datasets: "/datasets",
  scenario: "/scenario",
};

async function getJSON(path, params) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null) query.set(key, value);
  }
  const suffix = query.toString() ? `?${query}` : "";
  const response = await fetch(path + suffix);
  if (!response.ok) {
    // The message carries the path and the status because the alternative --
    // an empty diagram and a silent console -- is indistinguishable from a
    // dataset that genuinely has no lanes.
    throw new Error(`${path} responded ${response.status} ${response.statusText}`);
  }
  return response.json();
}

/** The dataset menu, in cycle order: default first, then alphabetical. */
export function fetchDatasets() {
  return getJSON(ENDPOINTS.datasets);
}

/**
 * The whole drawable payload: the pristine network, and every threat picture's
 * effects.
 *
 * One request per dataset, by design. There is no `threat` parameter -- the
 * server ships the pristine network always and the effects of each picture
 * inside `threat_pictures` -- so switching threat pictures mid-class is a
 * render pass over data already in hand rather than a fetch that can fail while
 * the room watches.
 */
export function fetchScenario(dataset) {
  return getJSON(ENDPOINTS.scenario, { dataset });
}
