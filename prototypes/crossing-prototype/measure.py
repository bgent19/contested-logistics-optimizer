"""THROWAWAY - wayfinder #23. Crossing geometry over #17's corrected coordinates.

Does a lane crossing read as a crossing at the back of the room, or as a junction
that is not in the graph?  This computes the geometry the eye is up against; the
HTML rig next door is where it gets looked at.

No dependencies.  python measure.py
"""
import itertools
import math

# ---- #17 section 3: the corrected theater.  STRAIT-3 moved 360 -> 300. --------
THEATER_NODES = {
    "HUB-ALPHA": (110, 250),
    "HUB-BRAVO": (110, 540),
    "LANE-J1":   (360, 190),
    "STRAIT-3":  (300, 400),
    "LANE-J2":   (360, 590),
    "AIRHEAD-7": (600, 120),
    "FOB-KILO":  (830, 270),
    "FOB-LIMA":  (830, 450),
    "FOB-MIKE":  (830, 630),
}
THEATER_EDGES = [
    ("e00", "HUB-ALPHA", "LANE-J1"),
    ("e01", "HUB-ALPHA", "STRAIT-3"),
    ("e02", "HUB-BRAVO", "LANE-J2"),
    ("e03", "LANE-J1",   "LANE-J2"),
    ("e04", "LANE-J1",   "AIRHEAD-7"),
    ("e05", "LANE-J1",   "FOB-KILO"),
    ("e06", "STRAIT-3",  "FOB-KILO"),
    ("e07", "LANE-J2",   "FOB-KILO"),
    ("e08", "LANE-J2",   "FOB-LIMA"),
    ("e09", "LANE-J2",   "FOB-MIKE"),
    ("e10", "AIRHEAD-7", "FOB-LIMA"),
    ("e11", "AIRHEAD-7", "FOB-MIKE"),
]
# #17 section 3, informative: the solved anchors on this layout.
THEATER_ANCHORS = {
    "e00": (235.0, 220.0), "e01": (205.0, 325.0), "e02": (235.0, 565.0),
    "e03": (360.0, 338.7), "e04": (480.0, 155.0), "e05": (595.0, 230.0),
    "e06": (565.0, 335.0), "e07": (595.0, 430.0), "e08": (595.0, 520.0),
    "e09": (595.0, 610.0), "e10": (771.5, 366.0), "e11": (778.2, 515.2),
}

# ---- #17 section 4 / #19: the re-authored Day 2 set. -------------------------
TEXTBOOK_NODES = {
    "s": (130, 360), "A": (380, 200), "C": (380, 520),
    "D": (640, 200), "B": (640, 520), "t": (860, 360),
}
TEXTBOOK_EDGES = [
    ("e00", "s", "A"), ("e01", "A", "B"), ("e02", "B", "t"), ("e03", "s", "C"),
    ("e04", "C", "B"), ("e05", "A", "D"), ("e06", "D", "t"),
]

# ---- the synthetic super-source / super-sink (#3: drawn as machinery) --------
SYN = {"S": (-30, 360), "T": (940, 360)}
SUPPLY = {"theater": ["HUB-ALPHA", "HUB-BRAVO"], "textbook": ["s"]}
DEMAND = {"theater": ["FOB-KILO", "FOB-LIMA", "FOB-MIKE"], "textbook": ["t"]}

# ---- #10 / #17 constants, none of them chosen here ---------------------------
R = 30.0            # node radius                              (#10 prototype B/C)
SMEAR = 6.9         # 2.2px blur at 0.32 scale                 (#10 back-row model)
LEGIBLE_GAP = 14.0  # ~2x smear                                (#17 section 1)
W_LANE = 4.5        # base lane stroke                         (#10 variant B)
W_PATH = 11.0       # augmenting path stroke                   (#10 variant B)
W_NAIVE = 6.0       # naive load stroke                        (#10 variant B)
W_VIOL = 11.0       # capacity violation stroke                (#10 variant B)
OFF_NAIVE = 9.0     # naive load parallel offset               (#10)
OFF_RESID = 11.0    # residual arc parallel offset             (#10)
OFF_PROMOTED = 22.0 # promoted reverse arc offset              (#20)


def seg(nodes, a, b, trim_a=R, trim_b=R + 6):
    """A lane as drawn: the chord between the two node rims.

    trim_b is R+6 rather than R because #10's renderer holds the arrowhead
    clear of the target rim.  The HTML rig next door uses the same numbers, so
    the two agree crossing for crossing.
    """
    (x1, y1), (x2, y2) = nodes[a], nodes[b]
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    return (x1 + dx / L * trim_a, y1 + dy / L * trim_a,
            x2 - dx / L * trim_b, y2 - dy / L * trim_b)


def intersect(p, q):
    """Proper interior intersection of two segments, or None."""
    x1, y1, x2, y2 = p
    x3, y3, x4, y4 = q
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-9:
        return None
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    if not (1e-6 < t < 1 - 1e-6 and 1e-6 < u < 1 - 1e-6):
        return None
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1), t, u)


def angle_between(p, q):
    """Acute angle between two segments, degrees."""
    a = math.atan2(p[3] - p[1], p[2] - p[0])
    b = math.atan2(q[3] - q[1], q[2] - q[0])
    d = math.degrees(abs(a - b)) % 180.0
    return min(d, 180.0 - d)


def blob(w1, w2, theta_deg):
    """The merged mark two crossing strokes make once the room blurs them.

    Each stroke is w wide and smears to w + SMEAR.  Where they cross, the union
    is a parallelogram: the extent ALONG stroke 1 is set by how far stroke 2's
    smeared band reaches, which is (w2 + SMEAR) / sin(theta).  At a right angle
    that is just the band width; at a shallow angle it runs away.

    Returns (extent along 1, extent along 2, longest axis of the union).
    """
    s = math.sin(math.radians(theta_deg))
    b1 = (w2 + SMEAR) / s
    b2 = (w1 + SMEAR) / s
    # long diagonal of the parallelogram whose sides are b1 along u1 and b2 along u2
    diag = math.sqrt(b1 * b1 + b2 * b2 + 2 * b1 * b2 * math.cos(math.radians(theta_deg)))
    return b1, b2, diag


def crossings(nodes, edges, name, synth=None):
    segs = {eid: seg(nodes, a, b) for eid, a, b in edges}
    if synth:
        for n in synth[0]:
            segs["S>" + n] = seg({**nodes, **SYN}, "S", n, 22.0, R)
        for n in synth[1]:
            segs["%s>T" % n] = seg({**nodes, **SYN}, n, "T", R, 22.0)
    out = []
    for (e1, s1), (e2, s2) in itertools.combinations(segs.items(), 2):
        hit = intersect(s1, s2)
        if hit is None:
            continue
        x, y, _, _ = hit
        th = angle_between(s1, s2)
        out.append({"e1": e1, "e2": e2, "x": x, "y": y, "theta": th})
    for c in out:
        c["nearest_node"] = min(
            (math.hypot(c["x"] - p[0], c["y"] - p[1]), n) for n, p in nodes.items())
    return segs, out


def report(title, nodes, edges, anchors, synth):
    print("=" * 78)
    print(title)
    print("=" * 78)
    segs, xs = crossings(nodes, edges, title, synth)
    real = [c for c in xs if not c["e1"].count(">") and not c["e2"].count(">")]
    synx = [c for c in xs if c not in real]
    print("lane x lane crossings: %d   (+%d involving a synthetic S/T arc)"
          % (len(real), len(synx)))
    print()
    hdr = ("  %-9s %-9s %7s %7s %6s | %8s %8s %8s | %7s %-11s"
           % ("lane A", "lane B", "x", "y", "angle", "blobA", "blobB", "union",
              "d(node)", "nearest"))
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for c in sorted(xs, key=lambda c: c["theta"]):
        b1, b2, diag = blob(W_LANE, W_LANE, c["theta"])
        d, n = c["nearest_node"]
        print("  %-9s %-9s %7.1f %7.1f %5.1f%s | %8.1f %8.1f %8.1f | %7.1f %-11s"
              % (c["e1"], c["e2"], c["x"], c["y"], c["theta"], chr(176),
                 b1, b2, diag, d, n))
    print()

    if not xs:
        print("  nothing to measure.\n")
        return xs

    # --- is the blob node-sized? -------------------------------------------
    print("  node diameter is %.0f units.  A crossing blob whose union axis"
          % (2 * R))
    print("  approaches that is a mark the size of a node, sitting where the")
    print("  graph has no node.")
    print()
    for c in sorted(xs, key=lambda c: -blob(W_LANE, W_LANE, c["theta"])[2]):
        _, _, diag = blob(W_LANE, W_LANE, c["theta"])
        pct = diag / (2 * R) * 100
        print("    %-9s x %-9s  union %5.1f = %5.1f%% of a node" % (c["e1"], c["e2"], diag, pct))
    print()

    # --- the layers that make it worse -------------------------------------
    print("  Under the layers that are actually on:")
    print()
    print("    %-22s %8s %8s %8s" % ("case", "worst", "median", "best"))
    for label, w1, w2 in [
            ("two bare lanes", W_LANE, W_LANE),
            ("path x bare lane", W_PATH, W_LANE),
            ("path x violation", W_PATH, W_VIOL),
            ("naive x naive (4 strokes)", W_NAIVE, W_NAIVE)]:
        vals = sorted(blob(w1, w2, c["theta"])[2] for c in xs)
        print("    %-22s %8.1f %8.1f %8.1f" % (label, vals[-1], vals[len(vals) // 2], vals[0]))
    print()

    # --- the parallel-offset problem ---------------------------------------
    print("  Parallel-offset marks (#10 residual 11, naive 9; #20 promoted 22)")
    print("  multiply a crossing into several.  A crossing of two lanes that")
    print("  each carry a naive load presents 4 strokes; the outer pair are")
    print("  offset along each lane by 9/sin(theta) from the true crossing:")
    print()
    for c in sorted(xs, key=lambda c: c["theta"])[:4]:
        s = math.sin(math.radians(c["theta"]))
        print("    %-9s x %-9s  %5.1f%s -> secondary crossings at +/-%.1f and +/-%.1f units"
              % (c["e1"], c["e2"], c["theta"], chr(176), OFF_NAIVE / s, OFF_RESID / s))
    print()

    # --- anchors vs crossings, #17's rule 4 ---------------------------------
    if anchors:
        print("  #17 rule 4: an anchor must clear a crossing by 44.  Checked on")
        print("  lane x lane crossings only (which is what #17 solved against):")
        worst = []
        for eid, (ax, ay) in anchors.items():
            for c in real:
                worst.append((math.hypot(ax - c["x"], ay - c["y"]), eid, c["e1"], c["e2"]))
        worst.sort()
        for d, eid, e1, e2 in worst[:5]:
            flag = "OK" if d >= 44 else "VIOLATION"
            print("    anchor %-5s vs %-5s x %-5s : %6.1f  %s" % (eid, e1, e2, d, flag))
        print()

    # --- crossings near each other -----------------------------------------
    pairs = []
    for c1, c2 in itertools.combinations(xs, 2):
        pairs.append((math.hypot(c1["x"] - c2["x"], c1["y"] - c2["y"]),
                      c1["e1"], c1["e2"], c2["e1"], c2["e2"]))
    pairs.sort()
    if pairs:
        print("  Closest crossing-to-crossing distances (two blobs closer than")
        print("  ~2x smear = %.1f merge into one bigger one):" % (2 * SMEAR))
        for d, a1, a2, b1_, b2_ in pairs[:4]:
            print("    (%s x %s) - (%s x %s) : %.1f" % (a1, a2, b1_, b2_, d))
        print()
    return xs


def casing(xs):
    """How wide must a knockout casing be, and what does it cost?

    A casing is a background-coloured stroke drawn UNDER the over-mark and OVER
    the under-mark, so the over-mark punches a visible hole through the one it
    crosses.  The hole, measured along the under-lane, is casing_w / sin(theta) -
    so the WORST case is the crossing nearest a right angle, not the shallowest.
    That is the opposite of every other quantity on this page.
    """
    print("=" * 78)
    print("KNOCKOUT CASING - how wide, and does it fit in space already reserved?")
    print("=" * 78)
    print()
    print("  #17's legible gap is %.0f (2x the %.1f-unit smear).  The hole a casing"
          % (LEGIBLE_GAP, SMEAR))
    print("  of width w opens in the lane it crosses is w / sin(theta), so the")
    print("  binding case is the crossing CLOSEST to 90 degrees:")
    print()
    worst = max(xs, key=lambda c: math.sin(math.radians(c["theta"])))
    print("    tightest crossing: %s x %s at %.1f%s" % (worst["e1"], worst["e2"], worst["theta"], chr(176)))
    need = LEGIBLE_GAP * math.sin(math.radians(worst["theta"]))
    print("    casing width needed there: %.0f x sin(%.1f%s) = %.1f"
          % (LEGIBLE_GAP, worst["theta"], chr(176), need))
    print()
    print("  So a casing of %.0f units - #17's legible gap, used verbatim - opens a"
          % LEGIBLE_GAP)
    print("  legible hole at EVERY crossing on the board, with margin to spare:")
    print()
    print("    %-9s %-9s %6s %9s %9s" % ("lane A", "lane B", "angle", "hole", "vs 2xsmear"))
    for c in sorted(xs, key=lambda c: -c["theta"]):
        hole = LEGIBLE_GAP / math.sin(math.radians(c["theta"]))
        print("    %-9s %-9s %5.1f%s %9.1f %8.2fx"
              % (c["e1"], c["e2"], c["theta"], chr(176), hole, hole / (2 * SMEAR)))
    print()
    half = LEGIBLE_GAP / 2
    print("  Cost against #17's reserved space.  The casing is a stroke ON the lane,")
    print("  so it occupies +/-%.1f of the lane centreline." % half)
    print("    #17 lane band half-width            : 14.0   -> casing fits, %.1f to spare"
          % (14.0 - half))
    print("    #10 residual arc offset             : %.1f   -> clear by %.1f" % (OFF_RESID, OFF_RESID - half))
    print("    #10 naive load offset               : %.1f    -> clear by %.1f" % (OFF_NAIVE, OFF_NAIVE - half))
    print("    #20 promoted reverse arc offset     : %.1f   -> clear by %.1f" % (OFF_PROMOTED, OFF_PROMOTED - half))
    print()
    print("  The casing spends NO space that #17 had not already reserved for the")
    print("  lane band, and collides with no offset mark on the board.")
    print()


def ordering(xs, edges):
    """Who owns crossing order?

    Any TOTAL order over the lanes induces a consistent over/under at every
    crossing - cycles are impossible by construction, so feasibility is not the
    question.  The question is which order, and what it is coupled to.
    """
    print("=" * 78)
    print("WHO OWNS CROSSING ORDER")
    print("=" * 78)
    print()
    ids = [e[0] for e in edges]
    print("  Any total order over the %d lanes is acyclic by construction, so a" % len(ids))
    print("  single global paint order resolves all %d crossings with no conflict." % len(xs))
    print("  Under #5 (build once, paint order = DOM order) the default total")
    print("  order is the JSON edges array.")
    print()
    print("  Which lane ends up on top under file order:")
    print()
    rank = {e: i for i, e in enumerate(ids)}
    for c in sorted(xs, key=lambda c: c["theta"]):
        over, under = (c["e2"], c["e1"]) if rank[c["e2"]] > rank[c["e1"]] else (c["e1"], c["e2"])
        print("    %s x %s  ->  %s over %s" % (c["e1"], c["e2"], over, under))
    print()
    print("  THE TRAP: the JSON edges array is ALREADY load-bearing twice -")
    print("  #15 (only 25%% of orderings show Day 2's cancellation) and #22 (only")
    print("  66.7%% preserve the interdiction divergence), both because _build adds")
    print("  lanes in file order and BFS scans adj[u] in insertion order.  Deriving")
    print("  paint order from the same array is a THIRD coupling to it.")
    print()


def live(xs):
    """Which crossings are LIVE - carrying an annotation on at least one side?

    A worry about "8 crossings at full strength" is only as big as the number of
    crossings the eye is actually asked to trace through.  The layer sets below
    are #3's per-view defaults; the annotated lane sets are the ones the map
    already records.
    """
    print("=" * 78)
    print("WHICH CROSSINGS ARE LIVE, PER VIEW")
    print("=" * 78)
    print()
    # the augmenting path used by the rig: HUB-ALPHA -> LANE-J1 -> FOB-KILO
    path = {"e00", "e05"}
    cut = {"e05", "e06", "e07"}
    naive = {"e02", "e09", "e00", "e05", "e03"}
    violations = {"e02", "e09"}
    views = [
        ("Pristine (opening screen)", set(), "nothing is being traced"),
        ("Flow & Cut - path beat", path, "the augmenting path"),
        ("Flow & Cut - cut beat", cut, "the three severed lanes"),
        ("Cost & Risk - naive", naive, "the naive load overlay"),
        ("Cost & Risk - violations", violations, "the two over-capacity lanes"),
    ]
    for name, marked, what in views:
        both = [c for c in xs if c["e1"] in marked and c["e2"] in marked]
        one = [c for c in xs if (c["e1"] in marked) != (c["e2"] in marked)]
        print("  %-28s  %s" % (name, what))
        print("      annotated x annotated : %d %s"
              % (len(both), "".join(" (%s x %s)" % (c["e1"], c["e2"]) for c in both)))
        print("      annotated x bare lane : %d %s"
              % (len(one), "".join(" (%s x %s)" % (c["e1"], c["e2"]) for c in one)))
        print()
    print("  The two worst blobs measured above - path x violation (77% of a node)")
    print("  and naive x naive (56%) - both need two ANNOTATED lanes to cross.")
    print("  On this theater, in every view, that count is zero.  The worst case")
    print("  that actually occurs is a single annotation crossing a bare lane.")
    print()


if __name__ == "__main__":
    xs = report("THEATER - #17 corrected coordinates (STRAIT-3 at 300,400)",
                THEATER_NODES, THEATER_EDGES, THEATER_ANCHORS,
                (SUPPLY["theater"], DEMAND["theater"]))
    report("DAY 2 - #15 network, #17 re-authored coordinates",
           TEXTBOOK_NODES, TEXTBOOK_EDGES, None,
           (SUPPLY["textbook"], DEMAND["textbook"]))
    real = [c for c in xs if ">" not in c["e1"] and ">" not in c["e2"]]
    casing(real)
    ordering(real, THEATER_EDGES)
    live(real)
