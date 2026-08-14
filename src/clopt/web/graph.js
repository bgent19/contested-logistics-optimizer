/* Builds the persistent DOM once from topology, and owns the handle map.
 *
 * Build once, then mutate. At startup this module emits one element per node
 * and per lane, keyed by id, and never changes the structure again. Every later
 * state change is a render pass that updates attributes and classes on elements
 * that already exist -- which is why `render.js` imports nothing from here
 * except the handles: appending an element from the render pass would be a
 * visible import-direction violation rather than an invisible line in a diff.
 *
 * Four things are solved here, once, against the PRISTINE network, and reused
 * unchanged under every threat picture, interdiction and A/B flip. Solving them
 * per-render would let marks slide when a lane is removed, and the flip-book
 * has no transitions to hide the jump.
 *
 *   1. the layered fallback for nodes with no authored coordinates
 *   2. the directed-pair -> {edgeId, direction} lookup
 *   3. the lane anchor solve
 *   4. the crossing solve
 */

const SVG_NS = "http://www.w3.org/2000/svg";

/* Geometry, not appearance -- these are the numbers the clearance arithmetic
 * was done against, so they live beside that arithmetic rather than in the
 * token block. Changing one invalidates the clearances in
 * `tests/layout_geometry.py`. */
const NODE_R = 30;
const TERMINAL_R = 22;
const LANE_GAP = 6;        /* air between a lane's end and the node it meets */

/* The derived terminals sit outside the authored coordinate range, pinned at
 * the horizontal extremes, so a min cut later reads as the S-T partition it is
 * defined to be.
 *
 * Derived from the dataset rather than hardcoded: a fixed pair of x values is
 * only "the extremes" for a theater as wide as today's, and a wider dataset
 * would quietly draw its super-source *inside* the graph, where the S-T
 * partition stops reading as a partition. The clamp keeps both terminals and
 * their discs inside the viewBox whatever the data does. */
const TERMINAL_MARGIN = 120;   /* clear air between the graph and a terminal */
const TERMINAL_Y = 360;
const VIEWBOX = { left: -60, right: 1000 };

/* The anchor solve's constants. Mirrored in `tests/layout_geometry.py`; see
 * `anchorSolve`. */
const ANCHOR_CLEAR_OF_NODE = 74;
const ANCHOR_CLEAR_OF_ANCHOR = 74;
const ANCHOR_CLEAR_OF_CROSSING = 44;
const ANCHOR_STEP = 2;
const CASING_WIDTH = 14;

/* The layered fallback's spacing. Only reached by a dataset that ships without
 * coordinates, which is the point: a new theater file can be seen before every
 * coordinate has been hand-authored. */
const FALLBACK = { x0: 60, dx: 200, y0: 90, dy: 130 };

/** The handle map, `{edgeId: bundle}` and `{nodeId: bundle}`. See `buildGraph`. */
export const handles = { nodes: new Map(), edges: new Map(), terminals: new Map() };

/** The frozen solves, filled by `buildGraph` and read by `render.js`. */
export const frozen = {
  positions: new Map(),    /* nodeId -> {x, y}, terminals included */
  anchors: new Map(),      /* edgeId -> {x, y} */
  crossings: [],           /* {point, angle, lanes: [edgeId, edgeId]} */
  directed: new Map(),     /* "src>dst" -> {edgeId, direction} */
  terminalLinks: [],       /* {nodeId, role} for each derived S/T arc */
};

function element(name, attributes) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes || {})) {
    node.setAttribute(key, value);
  }
  return node;
}

/* ---- 1. the layered fallback ---------------------------------------------
 * Supply on the left, demand on the right, transit spread across the middle by
 * how far it sits from the nearest supply node. Crude on purpose: it exists so
 * that adding a theater file does not require hand-authoring every coordinate
 * before the file can be looked at, not so that anybody teaches from it.
 */
function layeredFallback(network, placed) {
  const unplaced = network.nodes.filter((node) => !placed.has(node.id));
  if (unplaced.length === 0) return new Map();

  const neighbours = new Map(network.nodes.map((node) => [node.id, []]));
  for (const edge of network.edges) {
    neighbours.get(edge.src).push(edge.dst);
    if (edge.bidirectional) neighbours.get(edge.dst).push(edge.src);
  }

  const depth = new Map();
  const queue = [];
  for (const node of network.nodes) {
    if (node.kind === "supply") {
      depth.set(node.id, 0);
      queue.push(node.id);
    }
  }
  while (queue.length) {
    const id = queue.shift();
    for (const next of neighbours.get(id) || []) {
      if (!depth.has(next)) {
        depth.set(next, depth.get(id) + 1);
        queue.push(next);
      }
    }
  }

  const maxDepth = Math.max(0, ...depth.values());
  const columns = new Map();
  const positions = new Map();
  for (const node of unplaced) {
    /* A demand node with no path from any supply still belongs on the right,
     * where the class expects to find it. */
    const column = node.kind === "demand"
      ? maxDepth + 1
      : (depth.has(node.id) ? depth.get(node.id) : 1);
    const row = columns.get(column) || 0;
    columns.set(column, row + 1);
    positions.set(node.id, {
      x: FALLBACK.x0 + column * FALLBACK.dx,
      y: FALLBACK.y0 + row * FALLBACK.dy,
    });
  }
  return positions;
}

/* ---- 2. the directed-pair lookup -----------------------------------------
 * This must exist regardless of what needs it, because reverse arcs have no id
 * by construction: a bidirectional lane is ONE stored edge and TWO arcs in the
 * solver, and every result endpoint answers in `{src, dst}` pairs. Without this
 * map, matching a solver result back to the lane it belongs to is a scan.
 */
function directedLookup(edges) {
  const map = new Map();
  for (const edge of edges) {
    map.set(`${edge.src}>${edge.dst}`, { edgeId: edge.id, direction: "forward" });
    if (edge.bidirectional) {
      map.set(`${edge.dst}>${edge.src}`, { edgeId: edge.id, direction: "reverse" });
    }
  }
  return map;
}

/** The lane a directed pair belongs to, and which way along it. */
export function laneFor(src, dst) {
  return frozen.directed.get(`${src}>${dst}`) || null;
}

/* ---- geometry primitives -------------------------------------------------- */
function distance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function segmentIntersection(a, b, c, d) {
  const denominator = (a.x - b.x) * (c.y - d.y) - (a.y - b.y) * (c.x - d.x);
  if (Math.abs(denominator) < 1e-12) return null;
  const t = ((a.x - c.x) * (c.y - d.y) - (a.y - c.y) * (c.x - d.x)) / denominator;
  const u = ((a.x - c.x) * (a.y - b.y) - (a.y - c.y) * (a.x - b.x)) / denominator;
  if (t > 1e-9 && t < 1 - 1e-9 && u > 1e-9 && u < 1 - 1e-9) {
    return { x: a.x + t * (b.x - a.x), y: a.y + t * (b.y - a.y) };
  }
  return null;
}

function crossingAngle(a, b, c, d) {
  const ux = b.x - a.x;
  const uy = b.y - a.y;
  const vx = d.x - c.x;
  const vy = d.y - c.y;
  const magnitude = Math.hypot(ux, uy) * Math.hypot(vx, vy);
  if (magnitude === 0) return 0;
  return Math.acos(Math.min(1, Math.abs(ux * vx + uy * vy) / magnitude)) * 180 / Math.PI;
}

/* ---- 4. the crossing solve ------------------------------------------------
 * A crossing gets a background-coloured knockout casing, and the casing lives
 * on the ANNOTATION TIER ONLY -- never lane over lane. That is what leaves the
 * pristine opening screen with zero marks on it: the stubs are in the DOM from
 * the first paint and show nothing until a layer that paints over the lanes is
 * switched on.
 *
 * The named worry -- a crossing reading as a junction -- is not the real
 * failure. The literature finds crossings degrade *path search* and not node
 * locating, which inverts it: the crossing costs nothing while the class is
 * reading the map, and costs when the class is tracing a route through it. So
 * the break is bought exactly when a route is being traced, and not before.
 *
 * Casing width is `14 / sin(theta)` measured along the lane. The binding case
 * is the crossing nearest 90 degrees, not the shallowest, because `1/sin` is
 * smallest there -- giving 14, which fits inside the lane band already
 * reserved, so nothing moves. It spends no hue and no glyph.
 */
function crossingSolve(edges, positions) {
  const found = [];
  for (let i = 0; i < edges.length; i += 1) {
    for (let j = i + 1; j < edges.length; j += 1) {
      const one = edges[i];
      const other = edges[j];
      const ids = new Set([one.src, one.dst, other.src, other.dst]);
      if (ids.size < 4) continue;   /* a shared node is a junction, not a crossing */
      const a = positions.get(one.src);
      const b = positions.get(one.dst);
      const c = positions.get(other.src);
      const d = positions.get(other.dst);
      const point = segmentIntersection(a, b, c, d);
      if (!point) continue;
      const angle = crossingAngle(a, b, c, d);
      found.push({
        point,
        angle,
        /* Along-lane length of the break. Guarded against a vanishing sine
         * that no shipped layout reaches but a future coordinate edit could. */
        length: CASING_WIDTH / Math.max(Math.sin(angle * Math.PI / 180), 0.2),
        lanes: [one.id, other.id],
      });
    }
  }
  return found;
}

/* ---- 3. the lane anchor solve --------------------------------------------
 * One anchor per lane carries its flow numeral, its statistics and its min-cut
 * tick, and never moves. A numeral must not jump between beats while the
 * instructor is talking, so the anchor is solved once here and frozen.
 *
 * The problem that forced it: a lane drawn *through* a node is a topology lie
 * that only coordinates can fix; everything else on the list is label
 * placement. Holding numerals at lane midpoints and moving nodes instead,
 * 253,422 candidate layouts found ZERO feasible -- all bottoming out on a
 * numeral sitting on a crossing that no node position can move. Introduce the
 * sliding anchor and the same theater is feasible with one node moved 60 units,
 * with 9 of 12 anchors still on the exact midpoint.
 *
 * MIRRORED by `solve_anchors` in `tests/layout_geometry.py`, which is where the
 * rule is written down and where the shipped datasets are checked against it.
 * Keep the two identical. The mirror is exact for a fully-authored dataset --
 * which every shipped theater is, and which the test requires before it checks
 * anything.
 */
function anchorSolve(edges, positions, crossings) {
  const nodes = [...positions.values()];
  const crossingPoints = crossings.map((crossing) => crossing.point);
  const anchors = new Map();
  const placed = [];

  /* Stored-edge order -- the file's order, which is already the contract for
   * edge ids. Greedy and order-dependent, deliberately: a backtracking search
   * would be a better solver and a worse specification, because a fifty-line
   * search is not something a second implementation can be trusted to match. */
  for (const edge of edges) {
    const a = positions.get(edge.src);
    const b = positions.get(edge.dst);
    const length = distance(a, b);
    if (length === 0) {
      anchors.set(edge.id, null);
      continue;
    }
    const midpoint = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const ux = (b.x - a.x) / length;
    const uy = (b.y - a.y) / length;
    const travelLimit = length / 2 - ANCHOR_CLEAR_OF_NODE;

    let chosen = null;
    for (let step = 0; chosen === null && step * ANCHOR_STEP <= travelLimit; step += 1) {
      const offset = step * ANCHOR_STEP;
      /* Midpoint first, then out in both directions; the negative side wins the
       * sign tie, so the answer is a function of the coordinates alone. */
      for (const sign of (step === 0 ? [0] : [-1, 1])) {
        const candidate = {
          x: midpoint.x + ux * offset * sign,
          y: midpoint.y + uy * offset * sign,
        };
        if (nodes.some((n) => distance(candidate, n) < ANCHOR_CLEAR_OF_NODE)) continue;
        if (crossingPoints.some((p) => distance(candidate, p) < ANCHOR_CLEAR_OF_CROSSING)) continue;
        if (placed.some((p) => distance(candidate, p) < ANCHOR_CLEAR_OF_ANCHOR)) continue;
        chosen = candidate;
        break;
      }
    }

    /* No feasible point: fall back to the midpoint rather than dropping the
     * numeral. A numeral in a tight spot can be read; a missing one cannot be
     * noticed. The Python mirror returns `None` here instead, because a test
     * must fail loudly on this case -- which is where it should be caught,
     * long before a class.
     *
     * That is the ONE place the two implementations differ, and the divergence
     * is confined to the lane itself on purpose: the fallback midpoint is NOT
     * pushed onto `placed`, exactly as the Python skips it. Were it pushed,
     * one infeasible lane would shift every anchor solved after it and the two
     * implementations would disagree about the whole rest of the diagram. */
    anchors.set(edge.id, chosen || midpoint);
    if (chosen !== null) placed.push(chosen);
  }
  return anchors;
}

/* ---- the derived terminals ------------------------------------------------
 * S connects to every supply node with positive quantity, T from every demand
 * node with positive quantity -- mirroring the solver. The scenario payload
 * ships no synthetic nodes because it is a faithful mirror of the file the
 * instructor edits, so they are derived here instead.
 *
 * Accepted cost, stated rather than discovered: "who connects to a terminal"
 * now lives in two places, here and in `clopt.throughput`. If the solver's rule
 * changes, this is the second site.
 */
function terminalLinks(nodes) {
  const links = [];
  for (const node of nodes) {
    if (node.kind === "supply" && node.quantity > 0) {
      links.push({ nodeId: node.id, role: "S" });
    }
    if (node.kind === "demand" && node.quantity > 0) {
      links.push({ nodeId: node.id, role: "T" });
    }
  }
  return links;
}

/* ---- the build ------------------------------------------------------------ */
function clearChildren(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/**
 * Emit the whole diagram, once, for one dataset.
 *
 * Called once per dataset and never again for that dataset. The teardown at the
 * top is not a structural change under the build-once rule -- it is the end of
 * one dataset's DOM and the start of another's.
 */
export function buildGraph(svg, payload) {
  const network = payload.network;
  const tiers = {
    lanes: svg.querySelector("#tier-lanes"),
    nodes: svg.querySelector("#tier-nodes"),
    annotation: svg.querySelector("#tier-annotation"),
  };
  for (const tier of Object.values(tiers)) clearChildren(tier);
  clearChildren(document.getElementById("ledger-rows"));
  handles.nodes.clear();
  handles.edges.clear();
  handles.terminals.clear();

  /* -- positions: authored, then the fallback for anything unplaced -------- */
  const positions = new Map();
  for (const node of network.nodes) {
    if (node.x !== null && node.y !== null) positions.set(node.id, { x: node.x, y: node.y });
  }
  for (const [id, point] of layeredFallback(network, positions)) positions.set(id, point);

  /* The four frozen solves, all against the pristine network. The terminals are
   * deliberately NOT in the solves: they are derived machinery pinned outside
   * the authored coordinate range, and letting them move an anchor would put a
   * fact the authored layout cannot see into the layout's own arithmetic. */
  frozen.crossings = crossingSolve(network.edges, positions);
  frozen.anchors = anchorSolve(network.edges, positions, frozen.crossings);
  frozen.directed = directedLookup(network.edges);
  frozen.terminalLinks = terminalLinks(network.nodes);

  const xs = [...positions.values()].map((point) => point.x);
  const pad = TERMINAL_R + LANE_GAP;
  const clamp = (x) => Math.min(Math.max(x, VIEWBOX.left + pad), VIEWBOX.right - pad);
  positions.set("S", { x: clamp(Math.min(...xs) - TERMINAL_MARGIN), y: TERMINAL_Y });
  positions.set("T", { x: clamp(Math.max(...xs) + TERMINAL_MARGIN), y: TERMINAL_Y });
  frozen.positions = positions;

  /* -- lane tier ----------------------------------------------------------- */
  for (const link of frozen.terminalLinks) {
    const line = element("line", { class: "synth" });
    tiers.lanes.appendChild(line);
    handles.terminals.set(`${link.role}:${link.nodeId}`, { line, link });
  }

  const ledgerRows = document.getElementById("ledger-rows");
  for (const edge of network.edges) {
    const group = element("g", { class: "lane-group", "data-edge": edge.id });
    const line = element("line", { class: "lane" });
    const glyphOne = element("line", { class: "removed-glyph" });
    const glyphTwo = element("line", { class: "removed-glyph" });
    group.appendChild(line);
    group.appendChild(glyphOne);
    group.appendChild(glyphTwo);
    tiers.lanes.appendChild(group);

    /* One handle bundle per domain object, spanning canvas and panel. The
     * ledger row is built in this same topology pass because it IS the same
     * domain object -- which makes row-to-lane identity structural rather than
     * a lookup performed later and possibly wrongly. */
    const row = document.createElement("tr");
    row.dataset.edge = edge.id;
    const cells = [edge.id, edge.src, edge.dst].map((text) => {
      const cell = document.createElement("td");
      cell.textContent = text;
      return cell;
    });
    for (const cell of cells) row.appendChild(cell);
    ledgerRows.appendChild(row);

    handles.edges.set(edge.id, {
      edge,
      group,
      line,
      glyphs: [glyphOne, glyphTwo],
      canvasLabel: null,     /* filled below, on the annotation tier */
      ledgerRow: row,
      casingStubs: [],
    });
  }

  /* -- node tier ----------------------------------------------------------- */
  for (const role of ["S", "T"]) {
    const group = element("g", { class: "terminal", "data-terminal": role });
    const circle = element("circle", { r: TERMINAL_R });
    const text = element("text");
    text.textContent = role;
    group.appendChild(circle);
    group.appendChild(text);
    tiers.nodes.appendChild(group);
    handles.terminals.set(role, { group, circle, text });
  }

  for (const node of network.nodes) {
    const group = element("g", { class: `node ${node.kind}`, "data-node": node.id });
    const circle = element("circle", { r: NODE_R });
    const id = element("text", { class: "node-id" });
    const quantity = element("text", { class: "node-quantity" });
    id.textContent = node.id;
    quantity.textContent = node.quantity ? String(node.quantity) : "";
    group.appendChild(circle);
    group.appendChild(id);
    group.appendChild(quantity);
    tiers.nodes.appendChild(group);
    handles.nodes.set(node.id, { node, group, circle, id, quantity });
  }

  /* -- annotation tier ------------------------------------------------------
   * Two subgroups, and the order is the rule: casings knock out what is beneath
   * them, then marks paint over the casings. Within each subgroup the order is
   * arbitrary. */
  const casings = element("g", { id: "casings" });
  const marks = element("g", { id: "marks" });
  tiers.annotation.appendChild(casings);
  tiers.annotation.appendChild(marks);

  for (const crossing of frozen.crossings) {
    for (const edgeId of crossing.lanes) {
      const stub = element("line", { class: "casing" });
      casings.appendChild(stub);
      handles.edges.get(edgeId).casingStubs.push({ stub, crossing });
    }
  }

  for (const edge of network.edges) {
    const bundle = handles.edges.get(edge.id);
    /* Two texts share one anchor and one plate: the lane's static statistics
     * (capacity, cost, risk) and the flow the solver put on it. They are
     * separate elements rather than one because the layers that show them are
     * switched independently. `flow` gets its content in a later ticket; the
     * element exists from here so that nothing structural changes when it
     * does. */
    const plate = element("rect", { class: "anchor-plate" });
    const stats = element("text", { class: "lane-label" });
    const flow = element("text", { class: "anchor-label" });
    marks.appendChild(plate);
    marks.appendChild(stats);
    marks.appendChild(flow);
    bundle.canvasLabel = { plate, stats, flow };
  }

  return handles;
}

/** Geometry the render pass needs and must not recompute differently. */
export const geometry = { NODE_R, TERMINAL_R, LANE_GAP };
