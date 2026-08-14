"""Plane geometry over an authored theater layout -- no DOM, no browser.

The frontend is verified from Python or not at all (issue #39), so the checks
that protect the hand-authored coordinates are arithmetic over the JSON in
`data/`. This module holds the primitives and the numbers; `test_scenarios.py`
holds the assertions.

**This module is one half of a mirrored pair.** `src/clopt/web/graph.js` solves
the same lane anchors, at load, for the drawing. The two implementations must
agree, and nothing mechanical enforces that -- so the algorithm is spelled out
once, here, in `solve_anchors`, and `graph.js` carries a comment pointing back
at this file. The mirror is deliberate rather than accidental: the alternative
is shipping anchor positions in the `/scenario` payload, which would put
diagram layout into an API contract that is otherwise a faithful echo of the
file the instructor edits.
"""

import itertools
import math
from typing import Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float]
Lane = Tuple[str, str]

# ---- the clearances ---------------------------------------------------------
# Every number is *derived from mark geometry*, not chosen to fit the current
# layout: each is the radius the mark it names actually occupies, so a value
# here changes only when a mark's size changes.

# A lane passing a node it does not touch. Node radius 26 + stroke, plus the
# lane's own half-width and a hair of air, so the lane does not read as
# terminating at the node it grazes.
LANE_CLEAR_OF_NODE = 58.0

# A lane anchor carries a flow numeral, a statistic and a min-cut tick. All
# three sit in a stack about that tall, so the anchor needs this much room from
# any node and from any other anchor, or two lanes' numerals interleave.
ANCHOR_CLEAR_OF_NODE = 74.0
ANCHOR_CLEAR_OF_ANCHOR = 74.0

# A crossing wears a knockout casing 14 units wide (see `CASING_WIDTH`). The
# anchor must clear the casing plus half a numeral, or the break in the lane
# lands under the number that break was cut for.
ANCHOR_CLEAR_OF_CROSSING = 44.0

# Two node plates, side by side, with their labels.
NODE_CLEAR_OF_NODE = 90.8

# Below this a lane cannot carry an anchor at all, because the anchor must
# clear ANCHOR_CLEAR_OF_NODE from BOTH of its own endpoints -- so the shortest
# lane with any feasible anchor position is exactly twice that clearance, and
# at that length the midpoint is the only candidate.
#
# The spec (issue #39) names 120 here. That number is not consistent with the
# 74 it names one line earlier: 2 * 74 is 148, and on a 120-unit lane EVERY
# candidate position, midpoint included, sits inside 74 of an endpoint. A lane
# between 120 and 148 would therefore pass a 120 floor and then fail
# `test_every_lane_gets_a_clear_anchor` -- one requirement failing to catch
# what the next one does, which is how a floor comes to be believed and never
# fires. The derived value is used instead, and it is derived rather than
# restated so the two cannot drift apart again.
#
# Nothing shipped is affected: the shortest lane in `data/` is 242 units, which
# clears both numbers comfortably.
MIN_LANE_LENGTH = 2 * ANCHOR_CLEAR_OF_NODE

# The windfall the layout search never optimised for, and which therefore
# nothing protects. See `test_scenarios.py`.
MIN_CROSSING_ANGLE = 45.0

# The knockout casing's width, in diagram units. `14 / sin(theta)` along the
# lane; the binding case is the crossing nearest 90 degrees, not the shallowest,
# because `1 / sin` is *smallest* there -- and 14 fits inside the lane band
# already reserved, so nothing moves.
CASING_WIDTH = 14.0

# The anchor slide's step, in diagram units. Coarse enough that the search is
# trivial, fine enough that it never steps over a feasible window: the
# narrowest window any clearance leaves is far wider than this.
ANCHOR_STEP = 2.0


# ---- primitives -------------------------------------------------------------
def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def point_to_segment(p: Point, a: Point, b: Point) -> float:
    """Distance from `p` to the segment `ab` -- not to the infinite line.

    The segment matters: two lanes on the same bearing, end to end, are far
    apart as segments and zero apart as lines.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return distance(p, a)
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_squared
    t = max(0.0, min(1.0, t))
    return distance(p, (a[0] + t * dx, a[1] + t * dy))


def segment_intersection(a: Point, b: Point, c: Point, d: Point) -> Optional[Point]:
    """Where `ab` and `cd` cross, or `None`.

    Endpoints excluded on both segments: two lanes meeting at a shared node is
    a junction, which is the graph telling the truth, not a crossing.
    """
    x1, y1 = a
    x2, y2 = b
    x3, y3 = c
    x4, y4 = d
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) < 1e-12:
        return None   # parallel, or collinear -- no single crossing point
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denominator
    u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / denominator
    if 1e-9 < t < 1 - 1e-9 and 1e-9 < u < 1 - 1e-9:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def crossing_angle(a: Point, b: Point, c: Point, d: Point) -> float:
    """The acute angle between two segments, in degrees.

    Acute by construction -- a crossing at 30 degrees and one at 150 are the
    same crossing seen from the other side, and both are equally shallow.
    """
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = d[0] - c[0], d[1] - c[1]
    magnitude = math.hypot(ux, uy) * math.hypot(vx, vy)
    if magnitude == 0:
        return 0.0
    cosine = abs(ux * vx + uy * vy) / magnitude
    return math.degrees(math.acos(min(1.0, cosine)))


# ---- reading a dataset ------------------------------------------------------
def placed_nodes(payload: dict) -> Dict[str, Point]:
    """Every node carrying an authored coordinate.

    Half-authored nodes cannot occur -- `Node.__post_init__` refuses them --
    so testing `x` alone is enough.
    """
    return {
        n["id"]: (float(n["x"]), float(n["y"]))
        for n in payload["network"]["nodes"]
        if n.get("x") is not None
    }


def drawn_lanes(payload: dict, positions: Dict[str, Point]) -> List[Lane]:
    """The stored edges whose two endpoints are both placed.

    Stored edges, never the solver's arc expansion: a bidirectional lane is one
    line on the diagram, and counting it twice would report a crossing with
    itself.
    """
    return [
        (e["src"], e["dst"])
        for e in payload["network"]["edges"]
        if e["src"] in positions and e["dst"] in positions
    ]


def crossings(positions: Dict[str, Point], lanes: Sequence[Lane]) -> List[dict]:
    """Every lane-on-lane crossing, with the angle it crosses at."""
    found = []
    for (s1, d1), (s2, d2) in itertools.combinations(lanes, 2):
        if len({s1, d1, s2, d2}) < 4:
            continue   # a shared endpoint is a junction, not a crossing
        a, b, c, d = positions[s1], positions[d1], positions[s2], positions[d2]
        point = segment_intersection(a, b, c, d)
        if point is not None:
            found.append({
                "point": point,
                "angle": crossing_angle(a, b, c, d),
                "lanes": ((s1, d1), (s2, d2)),
            })
    return found


# ---- the anchor solve -------------------------------------------------------
def solve_anchors(positions: Dict[str, Point],
                  lanes: Sequence[Lane]) -> Dict[Lane, Optional[Point]]:
    """One anchor point per lane, slid along the lane until it is clear.

    Mirrored by `anchorSolve` in `src/clopt/web/graph.js`. Keep them identical.

    The rule, stated so both implementations can be checked against it:

    1. Lanes are taken in stored-edge order -- the file's order, which is
       already the contract for edge ids.
    2. Candidates are offsets from the lane's midpoint, tried in increasing
       distance: 0, then -step, +step, then -2*step, +2*step, and so on. The
       midpoint wins ties, and the negative side wins the sign tie, so the
       result is a function of the coordinates alone.
    3. A candidate is accepted if it clears every node, every crossing, and
       every anchor already placed.
    4. The slide stops where the anchor would come within `ANCHOR_CLEAR_OF_NODE`
       of its own endpoints. A lane with no accepted candidate returns `None`
       rather than a bad position -- an infeasible layout must be visible.

    **The one place the mirror is allowed to differ**, spelled out because
    "keep them identical" would otherwise be a lie: on an infeasible lane this
    returns `None` so the test fails loudly, while `graph.js` falls back to the
    midpoint so the numeral still draws. The difference is deliberately
    confined to that lane -- neither side lets the infeasible result take part
    in the `placed` list -- so every anchor solved *after* it is still
    identical on both sides. A future edit that pushes the fallback onto
    `placed` in `graph.js` would silently shift the rest of the diagram.

    Greedy and order-dependent, and deliberately so: a backtracking search would
    be a better solver and a worse *specification*, because a fifty-line search
    is not something a second implementation can be trusted to match.

    **How the mirror was checked, and how to check it again.** The two
    implementations were run against all three shipped datasets and compared
    coordinate by coordinate; they agreed to 6e-14, which is float noise. That
    check is not in this suite and must not be added to it -- it needs a
    JavaScript runtime, and a JS runtime in this repo is the second install path
    the no-test-runner rule exists to prevent. Re-run it by hand, from a
    scratch directory outside the repo, when either side changes: stub a DOM,
    import `graph.js`, call `buildGraph`, and diff `frozen.anchors` against what
    this function returns for the same dataset.
    """
    crossing_points = [c["point"] for c in crossings(positions, lanes)]
    nodes = list(positions.values())
    anchors: Dict[Lane, Optional[Point]] = {}
    placed: List[Point] = []

    for lane in lanes:
        a, b = positions[lane[0]], positions[lane[1]]
        length = distance(a, b)
        midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if length == 0:
            anchors[lane] = None
            continue
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        travel_limit = length / 2 - ANCHOR_CLEAR_OF_NODE

        chosen = None
        step_index = 0
        while chosen is None and step_index * ANCHOR_STEP <= travel_limit:
            offset = step_index * ANCHOR_STEP
            for sign in ((0,) if step_index == 0 else (-1, 1)):
                candidate = (midpoint[0] + ux * offset * sign,
                             midpoint[1] + uy * offset * sign)
                if any(distance(candidate, n) < ANCHOR_CLEAR_OF_NODE for n in nodes):
                    continue
                if any(distance(candidate, x) < ANCHOR_CLEAR_OF_CROSSING
                       for x in crossing_points):
                    continue
                if any(distance(candidate, p) < ANCHOR_CLEAR_OF_ANCHOR for p in placed):
                    continue
                chosen = candidate
                break
            step_index += 1

        anchors[lane] = chosen
        if chosen is not None:
            placed.append(chosen)
    return anchors
