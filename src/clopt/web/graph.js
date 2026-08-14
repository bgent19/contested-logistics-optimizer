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

/* ---- the panel's two always-present slots ---------------------------------
 * The panel is four fixed slots, built once per dataset in this same topology
 * pass and thereafter mutated only by class and text content. This module
 * builds the two that are present in all three views; the Pareto table and the
 * beat timeline arrive with the views that own them.
 *
 * The headline's slots are FIXED rather than per-view, so a number the
 * instructor read on the last beat is in the same place on this one -- an
 * empty slot says "not on this view" in the place the value would have been,
 * which is cheaper to read past than a dashboard that reshapes itself.
 */
const HEADLINE_SLOTS = [
  { id: "supply",      label: "Supply" },
  { id: "demand",      label: "Demand" },
  { id: "throughput",  label: "Flow" },
  { id: "cut",         label: "Cut" },
  /* "Struck", not "Cut": `Cut` above is the min cut's capacity, and two slots
   * a row apart both reading "cut" is exactly the ambiguity the instructor
   * would have to resolve out loud. */
  { id: "interdicted", label: "Struck" },
  { id: "violations",  label: "Over cap" },
];

/* The ledger's columns. Widths are percentages and the table is laid out
 * `fixed` -- see the note in `style.css`: an auto-laid-out table re-measures
 * its columns when a cell's text changes, so a two-digit flow becoming
 * three-digit would shift every column under the instructor's finger on a beat
 * that changed nothing else. */
const LEDGER_COLUMNS = [
  /* `cell` is the lane's own identity, written once at build time and never
   * again. A column with no `cell` is one the render pass owns: capacity and
   * risk move under a threat picture, and flow moves on every beat, so their
   * text -- and the formatting of it -- belongs to `render.js` alone. Giving
   * them a builder here too would put the same `toFixed(2)` in two modules,
   * and a retune of the precision would have to find both.
   *
   * The flow column exists from here regardless, empty until the Flow & Cut
   * view fills it: the ledger is built once per dataset, so a column added on
   * the day its numbers arrive would be a structural change to a built slot. */
  { key: "id",   head: "Lane", cell: (edge) => edge.id,  numeric: false },
  { key: "src",  head: "From", cell: (edge) => edge.src, numeric: false },
  { key: "dst",  head: "To",   cell: (edge) => edge.dst, numeric: false },
  { key: "cap",  head: "Cap",  numeric: true },
  { key: "cost", head: "Cost", cell: (edge) => edge.cost, numeric: true },
  { key: "risk", head: "Risk", numeric: true },
  { key: "flow", head: "Flow", numeric: true },
];

/** The handle map, `{edgeId: bundle}` and `{nodeId: bundle}`. See `buildGraph`. */
export const handles = {
  nodes: new Map(),
  edges: new Map(),
  terminals: new Map(),
  /** slotId -> the `<span>` holding that headline number. */
  headline: new Map(),
  /** The A/B pair's three cells, `{root, label, before, after}`. */
  delta: null,
};

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

/* ---- the ledger's frame ---------------------------------------------------
 * The `<col>` and `<th>` elements are built from `LEDGER_COLUMNS` rather than
 * written out in the markup, so the column list lives in exactly one place and
 * a column cannot gain a header without gaining a cell.
 *
 * Each `<col>` carries a class and no width: column widths are appearance and
 * belong to the stylesheet, like every other appearance value on the page.
 */
function buildLedgerFrame() {
  const cols = document.getElementById("ledger-cols");
  const head = document.getElementById("ledger-head");
  clearChildren(cols);
  clearChildren(head);

  const headRow = document.createElement("tr");
  for (const column of LEDGER_COLUMNS) {
    const col = document.createElement("col");
    col.className = `col-${column.key}`;
    cols.appendChild(col);

    const cell = document.createElement("th");
    cell.className = column.numeric ? "num" : "name";
    cell.textContent = column.head;
    headRow.appendChild(cell);
  }
  head.appendChild(headRow);
}

/* ---- the build ------------------------------------------------------------ */
function clearChildren(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/** An HTML element carrying a class and, optionally, some text. */
function el(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ---- the headline ---------------------------------------------------------
 * Six fixed stat cells and one A/B pair, built once and thereafter written
 * only through `textContent`. No `innerHTML` here or anywhere else in the
 * panel: a slot rebuilt from a string loses its handles, and the handle is
 * what makes a row and its lane demonstrably the same object.
 */
function buildHeadline() {
  const stats = document.getElementById("headline-stats");
  clearChildren(stats);
  handles.headline.clear();

  for (const slot of HEADLINE_SLOTS) {
    const cell = el("div", "stat");
    cell.appendChild(el("span", "stat-label", slot.label));
    const value = el("span", "stat-value", "—");
    cell.appendChild(value);
    stats.appendChild(cell);
    handles.headline.set(slot.id, value);
  }

  /* The one A/B pair. Its label is written by whichever view owns the flip,
   * because *which* number is being compared is the view's business -- but
   * there is only ever one pair, and it is always here. */
  const root = document.getElementById("headline-delta");
  clearChildren(root);
  const label = el("span", "delta-label");
  const before = el("span", "delta-before");
  const arrow = el("span", "delta-arrow", "→");
  const after = el("span", "delta-after");
  for (const part of [label, before, arrow, after]) root.appendChild(part);
  handles.delta = { root, label, before, after };
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
  handles.nodes.clear();
  handles.edges.clear();
  handles.terminals.clear();

  /* The panel's two always-present slots are built in this same pass, because
   * a ledger row and its lane are the same domain object -- see the bundle
   * below. */
  buildHeadline();
  const ledgerRows = document.getElementById("ledger-rows");
  clearChildren(ledgerRows);
  buildLedgerFrame();

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
     * a lookup performed later and possibly wrongly.
     *
     * The ledger carries one row per stored lane, ALWAYS, in stored-edge
     * order, and is never filtered to the cold ones. Filtering fails twice: it
     * reflows on every keypress -- the hot set is a two-to-four lane path that
     * changes at every beat, and rows shifting under a lane's name is the one
     * thing a flip-book does not survive -- and it empties itself at the
     * moment it should be fullest, on the pristine network, where an empty hot
     * set means *every* lane is hot and the instructor is most likely reading
     * lane numbers aloud. Showing everything and marking the hot rows gives
     * the ledger the job it needed anyway: it is the printed key to the
     * canvas. */
    const row = document.createElement("tr");
    row.dataset.edge = edge.id;
    const ledgerCells = {};
    for (const column of LEDGER_COLUMNS) {
      const cell = document.createElement("td");
      cell.className = column.numeric ? "num" : "name";
      if (column.cell) cell.textContent = column.cell(edge);
      row.appendChild(cell);
      ledgerCells[column.key] = cell;
    }
    ledgerRows.appendChild(row);

    handles.edges.set(edge.id, {
      edge,
      group,
      line,
      glyphs: [glyphOne, glyphTwo],
      canvasLabel: null,     /* filled below, on the annotation tier */
      ledgerRow: row,
      ledgerCells,
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
    /* Three texts on two rows, sharing one frozen anchor.
     *
     * The flow numeral takes the upper row and the lane's statistics the lower
     * one. `caps` and `costrisk` are two elements on the SAME row rather than
     * one text carrying all three numbers, because the catalog switches them
     * independently: Flow & Cut wants a capacity beside its flow and Cost &
     * Risk wants cost and risk instead, and a combined label put two unasked-for
     * numbers on screen in both. They are never both on by default -- and if
     * both are switched on by hand they overlap, which is one of the reasons
     * all-layers-on is not a legal preset.
     *
     * Each row carries its own plate, so a row that is switched off leaves no
     * unbacked rectangle behind. The whole lot lives in one group per lane so
     * that the scaffold tier can dim a lane and its numerals together, from one
     * class write. */
    const group = element("g", { class: "lane-marks", "data-edge": edge.id });
    const plateFlow = element("rect", { class: "anchor-plate plate-flow" });
    const flow = element("text", { class: "anchor-label" });
    const plateStat = element("rect", { class: "anchor-plate plate-stat" });
    const caps = element("text", { class: "lane-label lane-caps" });
    const costrisk = element("text", { class: "lane-label lane-costrisk" });
    for (const part of [plateFlow, flow, plateStat, caps, costrisk]) {
      group.appendChild(part);
    }
    marks.appendChild(group);
    bundle.canvasLabel = { group, plateFlow, flow, plateStat, caps, costrisk };
  }

  return handles;
}

/** Geometry the render pass needs and must not recompute differently. */
export const geometry = { NODE_R, TERMINAL_R, LANE_GAP };
