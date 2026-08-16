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
  maxflow: "/maxflow",
  interdict: "/interdict",
  sweep: "/sweep",
  naive: "/naive",
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

/**
 * Max throughput, the min-cut certificate and the WHOLE Edmonds-Karp trace, in
 * one request.
 *
 * `trace=true` always, from here, and that is the point of the wrapper: Day 2
 * steps through the augmentations in both directions at the front of the room,
 * so anything a keypress can reach is fetched before the first keypress. A
 * per-beat fetch could not be stepped backwards at speaking pace, and a beat
 * that awaits anything cannot be synchronous -- which is the property the whole
 * beat engine is built on.
 *
 * One response, not two. Throughput and cut capacity must be equal by max-flow
 * min-cut, and two numbers that must be equal, fetched separately, are two
 * numbers that can disagree one slot apart on the instructor's dashboard.
 */
export function fetchMaxflow(dataset, threat) {
  return getJSON(ENDPOINTS.maxflow, { dataset, threat, trace: "true" });
}

/**
 * Day 4's whole budget ladder -- every rung, both tracks -- in one request.
 *
 * `ladder=true` always, from here, for the same reason `trace=true` is always
 * set above: the ladder is walked at the front of the room in both directions,
 * so it is in hand before the first keypress. The alternative shape of this
 * call is the 2 x K x datasets requests a per-rung frontend would issue, each
 * of them a request that can fail while the room watches.
 *
 * No `method` parameter, and passing one is a 400 by design: a ladder runs both
 * methods by definition, so there is nothing for it to select. Where the ladder
 * ends, whether a rung collapsed and whether its two tracks parted ways are all
 * decided by the server, which is what keeps them facts a test can pin rather
 * than logic in a render pass.
 */
export function fetchLadder(dataset, threat) {
  return getJSON(ENDPOINTS.interdict, { dataset, threat, ladder: "true" });
}

/* ---- Day 1's matched pair -------------------------------------------------
 *
 * `/sweep` and `/naive` are a MATCHED PAIR and the pairing is the contract:
 * they take the same lambda list with the same default and answer with entries
 * in the same order, so the two arrays are indexed by the same position -- one
 * for the optimum, one for the collapse -- and the A/B flip is a swap at one
 * index rather than a join.
 *
 * Neither passes a `lambdas` parameter, and that is deliberate rather than an
 * omission. The server declares the default list once and both endpoints share
 * that one declaration, so sending it from here would be a third copy of the
 * eight values that could drift from the two that matter. The frontend's job is
 * to ask both endpoints the same question, and asking neither is the only way
 * to be sure it did.
 */

/**
 * The whole cost/risk frontier -- every lambda's optimum, plans included.
 *
 * One request per dataset, like the trace and the ladder above, and for the
 * same reason: Day 1 walks the frontier in both directions at the front of the
 * room, so anything a keypress can reach is in hand before the first keypress.
 */
export function fetchSweep(dataset, threat) {
  return getJSON(ENDPOINTS.sweep, { dataset, threat });
}

/**
 * Day 1's counterexample at every lambda -- one complete naive plan each.
 *
 * Complete rather than a delta against the lambda before it, which is the
 * server's choice and the right one: a delta format saves bytes on a payload
 * measured in kilobytes and buys a reconstruction step this frontend could get
 * wrong, mid-class, with nothing raised anywhere.
 */
export function fetchNaive(dataset, threat) {
  return getJSON(ENDPOINTS.naive, { dataset, threat });
}
