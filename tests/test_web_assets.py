"""The frontend is verified from Python or not at all.

No Playwright, no vitest, no jsdom, no headless Chromium, no screenshot diffing
-- not now, and not later. This is a *rule* rather than an absence, because the
zero-dependency posture is silently reversible: nobody adds a JS test runner in
one commit, they add it because one flaky thing needed checking, and then
installing this repo on the teaching laptop has a second install path.

The cost, named plainly: **no test here asserts that the SVG rendered.** The
picture is eyeballed, forever. What these tests do cover is the set of failures
that are invisible while authoring on a laptop and only appear in the room --
a stylesheet that reaches for the network, a token typo that silently drops a
declaration, and type that is legible at arm's length and gone at the back of a
classroom.
"""

import math
import os
import re
import warnings

import pytest

WEB = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src", "clopt", "web")
)

# The module inventory is fixed by the spec (issue #39), not left to the
# implementer, so it is asserted rather than globbed: a module that quietly
# disappears into another one is a design change, and should read as a failing
# test rather than as a tidy diff.
MODULES = [
    "index.html",   # SVG skeleton, view switcher, layer toggles, side panel
    "style.css",    # the :root token block and every appearance rule
    "api.js",       # every fetch -- the only module that knows endpoint URLs
    "state.js",     # the single app-state object and its mutators
    "graph.js",     # builds the persistent DOM once; owns the handle map
    "render.js",    # the one render pass -- geometry and classes only
    "views.js",     # the three views' default layer sets
]


def _read(name):
    with open(os.path.join(WEB, name), "r", encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def assets():
    """Every shipped web asset, by filename.

    Globbed rather than listed, so a file added later is scanned for outward
    references and token typos on the day it lands.
    """
    found = {
        name: _read(name)
        for name in sorted(os.listdir(WEB))
        if name.endswith((".html", ".css", ".js"))
    }
    assert found, f"no web assets found in {WEB}"
    return found


@pytest.fixture(scope="module")
def stylesheet(assets):
    return assets["style.css"]


@pytest.fixture(scope="module")
def viewbox_height(assets):
    """The `viewBox` height, which is the unit every type size is judged in.

    Parsed from the markup rather than restated here: a constant repeated in
    the test is a constant that can disagree with the page.
    """
    match = re.search(r'viewBox="\s*(-?[\d.]+)\s+(-?[\d.]+)\s+([\d.]+)\s+([\d.]+)',
                      assets["index.html"])
    assert match, "index.html has no <svg viewBox> to measure type against"
    return float(match.group(4))


# ---- (a) the offline guarantee ----------------------------------------------
# Ten lines; catastrophic failure mode. A web font or a CDN script is a network
# fetch, and a network fetch in a classroom is a live outage in front of a room.
OUTWARD = re.compile(
    r"""(?:src|href)\s*=\s*["']([^"']+)["']"""   # markup attributes
    r"""|@import\s+(?:url\()?["']?([^"')\s;]+)"""  # stylesheet imports
    r"""|url\(\s*["']?([^"')]+)""",                # every other CSS url()
    re.IGNORECASE,
)

# A scheme (`https:`, `data:`) or a protocol-relative prefix (`//cdn...`).
# Everything the page is allowed to reference is a bare relative path or a
# same-document fragment.
HAS_SCHEME = re.compile(r"^(?:[a-z][a-z0-9+.\-]*:|//)", re.IGNORECASE)


def test_no_asset_reaches_off_the_machine(assets):
    for name, text in assets.items():
        for match in OUTWARD.finditer(text):
            value = next(g for g in match.groups() if g is not None).strip()
            assert not HAS_SCHEME.match(value), (
                f"{name}: references {value!r}, which leaves this machine -- "
                f"a classroom has no network it can rely on"
            )


def test_no_asset_declares_a_web_font(assets):
    # Separate from the scan above because a @font-face can point outward
    # through `src:` in ways the attribute regex would not read, and because
    # the system font stack is the decision being protected.
    for name, text in assets.items():
        assert "@font-face" not in text, (
            f"{name}: declares @font-face; the page uses the system font stack "
            f"so that it never waits on a font that will not arrive"
        )


# ---- (b) token structure ----------------------------------------------------
# The strongest of the three. A mistyped `var(--residaul-dash)` with no
# fallback is invalid at computed-value time, so the declaration is *dropped*
# and the property falls back to `unset`. Nothing errors, nothing logs, the
# lane renders with a default stroke and looks entirely plausible -- and it is
# discovered on a projector, in front of a room.
TOKEN_USE = re.compile(r"var\(\s*(--[a-z0-9-]+)", re.IGNORECASE)
TOKEN_DEF = re.compile(r"^\s*(--[a-z0-9-]+)\s*:", re.IGNORECASE | re.MULTILINE)


def _defined_tokens(stylesheet):
    """Every token defined in the `:root` block.

    The `:root` block specifically, not every `--x:` in the file: a token
    defined inside some narrower selector is not part of the catalog the rest
    of the page is entitled to reach for.
    """
    match = re.search(r":root\s*\{(.*?)\}", stylesheet, re.DOTALL)
    assert match, "style.css has no :root token block"
    return set(TOKEN_DEF.findall(match.group(1)))


def test_every_referenced_token_is_defined(assets, stylesheet):
    defined = _defined_tokens(stylesheet)
    assert defined, ":root token block is empty"

    for name, text in assets.items():
        for token in TOKEN_USE.findall(text):
            assert token in defined, (
                f"{name}: uses {token}, which no :root definition provides. "
                f"The declaration will be dropped at computed-value time and "
                f"the mark will render plausibly wrong."
            )


def test_unreferenced_tokens_only_warn(assets, stylesheet):
    # Deliberately not a failure: the catalog can legitimately carry a token
    # ahead of the ticket that uses it, and failing here would push whoever
    # lands that ticket into deleting the definition instead.
    defined = _defined_tokens(stylesheet)
    used = {token for text in assets.values() for token in TOKEN_USE.findall(text)}
    unused = sorted(defined - used)
    if unused:
        warnings.warn(f"{len(unused)} token(s) defined but never referenced: {unused}")


# ---- (c) the type floor -----------------------------------------------------
# Scale-invariant by construction, and violating it is invisible while
# authoring on a laptop -- it fails only in the room.
TYPE_PREFIX = "--type-"     # canvas type, measured in diagram units
PANEL_PREFIX = "--panel-"   # panel type, measured in CSS pixels
HARD_FLOOR = 50             # H/50 == 2% of viewBox height
COMFORTABLE = 40            # H/40 == 2.5%


def _numeric_tokens(stylesheet):
    """Every token whose value is a bare number, with or without a CSS unit.

    The unit is captured and discarded on purpose. A panel size of `13px` and a
    canvas size of `13` are the same numeral in two incomparable units, and the
    whole point of the prefix rule below is that the floor knows which is
    which by *name* rather than by guessing from the unit.
    """
    match = re.search(r":root\s*\{(.*?)\}", stylesheet, re.DOTALL)
    values = {}
    for line in match.group(1).splitlines():
        found = re.match(r"\s*(--[a-z0-9-]+)\s*:\s*([\d.]+)(?:px|rem|em)?\s*(?:;|$)",
                         line, re.I)
        if found:
            values[found.group(1)] = float(found.group(2))
    return values


def test_canvas_type_clears_the_projector_floor(stylesheet, viewbox_height):
    """Every `--type-` token is at least 2% of the viewBox height.

    Matching is **starts-with, not substring**, and that is load-bearing in
    both directions. Without the prefix rule a panel token gets asserted
    against a ratio that means nothing for it; without starts-with matching a
    correctly-named `--panel-type-ledger` goes red on a perfectly valid value.
    """
    floor = viewbox_height / HARD_FLOOR
    type_tokens = {
        name: value
        for name, value in _numeric_tokens(stylesheet).items()
        if name.startswith(TYPE_PREFIX)
    }
    assert type_tokens, (
        f"no {TYPE_PREFIX}* token found -- the floor would pass vacuously"
    )

    for name, value in sorted(type_tokens.items()):
        assert value >= floor, (
            f"{name} is {value} diagram units, under the {floor:.1f} floor "
            f"(H/{HARD_FLOOR} of a {viewbox_height:.0f}-unit viewBox). It will "
            f"be legible on a laptop and gone from the back of the room."
        )


def test_panel_type_is_not_named_like_canvas_type(stylesheet):
    """The naming rule the floor depends on, asserted directly.

    Both halves are required. A panel size measured in CSS pixels has no
    business being compared against a fraction of the viewBox, so it must not
    wear the `--type-` prefix -- and this is the test that says so, rather than
    leaving it as a convention someone can break without noticing.
    """
    for name in _numeric_tokens(stylesheet):
        if name.startswith(PANEL_PREFIX):
            assert not name.startswith(TYPE_PREFIX), name   # unreachable by construction
        if name.startswith(TYPE_PREFIX):
            assert PANEL_PREFIX not in name, (
                f"{name} carries both prefixes; it will be judged against a "
                f"ratio that does not apply to it"
            )


# H/40 is the comfortable target and H/50 the hard floor. Only the floor is
# asserted, and there is deliberately no warning for sitting between the two:
# the authored sizes sit there on purpose, so such a warning would fire on every
# run forever, and a diagnostic that is always on is one nobody reads.


def test_the_casing_width_agrees_across_its_three_homes(assets, stylesheet):
    """`14` lives in three files, and nothing else makes them agree.

    The casing is a stroke that has to cover the lane it breaks: `graph.js`
    computes the stub's LENGTH from the width, `style.css` paints it at that
    width, and `tests/layout_geometry.py` derives the anchor clearance from it.
    Change one and the knockout stops covering the lane -- a break that no
    longer breaks, discovered on a projector. The duplication is unavoidable
    (a stylesheet cannot import a JS constant), so it is pinned instead.
    """
    from layout_geometry import CASING_WIDTH

    css = _numeric_tokens(stylesheet)["--casing-w"]
    js = re.search(r"const CASING_WIDTH\s*=\s*([\d.]+)", assets["graph.js"])
    assert js, "graph.js no longer declares CASING_WIDTH"

    assert css == float(js.group(1)) == CASING_WIDTH, (
        f"casing width disagrees: style.css {css}, graph.js {js.group(1)}, "
        f"layout_geometry.py {CASING_WIDTH}"
    )


# ---- structural rules -------------------------------------------------------
def test_the_module_inventory_is_what_the_spec_fixed():
    for name in MODULES:
        assert os.path.isfile(os.path.join(WEB, name)), (
            f"{name} is missing; the module split is fixed by the spec"
        )


# Endpoint paths this API actually serves. Confining them to one module keeps
# the blast radius of every API contract decision to one file.
ENDPOINTS = ["/scenario", "/datasets", "/allocate", "/route", "/sweep",
             "/naive", "/maxflow", "/interdict", "/health"]


COMMENT = re.compile(
    r"/\*.*?\*/"            # CSS and JS block comments
    r"|<!--.*?-->"          # markup comments
    r"|^[ \t]*//[^\n]*",    # whole-line JS comments
    re.DOTALL | re.MULTILINE,
)


def test_only_api_js_knows_an_endpoint_url(assets):
    for name, text in assets.items():
        if name == "api.js":
            continue
        # Comments are stripped first, so prose naming `/scenario` in a doc
        # block is documentation rather than a second place the URL lives.
        # Backticks stay in the quote set afterwards: in code, a backtick around
        # an endpoint path is a template literal and a genuine leak.
        code = COMMENT.sub(" ", text)
        literals = re.findall(r"""["'`](/[a-z][a-z0-9/_-]*)["'`]""", code, re.I)
        leaked = sorted(set(literals) & set(ENDPOINTS))
        assert not leaked, (
            f"{name}: contains endpoint URL(s) {leaked}. Every fetch and every "
            f"endpoint path belongs in api.js."
        )


# ---- the side panel (issue #40) ---------------------------------------------
# The panel is four fixed slots, built once per dataset and thereafter mutated
# only by class and text content. Three of its apparent content shapes were
# never components: the cut's certifying lane list and the interdicted subset
# are *subsets of the lanes*, so they are row states on the one ledger row --
# never separate DOM. Otherwise the same lane sits in the panel twice, in two
# renderings that can disagree.
ROW_STATES = ["in-cut", "removed", "violating", "on-path", "hot"]


def test_no_asset_writes_markup_as_a_string(assets):
    """No `innerHTML` after build, in any slot.

    The panel's whole discipline rests on this. A slot rebuilt from a string
    loses its handles, so the row that a lane's bundle points at stops being
    the row on screen -- and the two only disagree once some state is set,
    which is to say in front of a room rather than on the laptop.
    """
    forbidden = ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"]
    for name, text in assets.items():
        code = COMMENT.sub(" ", text)
        for token in forbidden:
            assert token not in code, (
                f"{name}: uses {token}. Every slot is built once with "
                f"createElement and mutated only by class and textContent."
            )


def test_every_row_state_is_a_class_on_the_one_ledger_row(assets, stylesheet):
    """The five row states exist as classes, and something computes each.

    Checked from both ends on purpose. A state painted by the stylesheet but
    never computed is a rule that has never fired; a state computed but never
    painted is a class that shows nothing. Either way the lane subset it was
    meant to certify is invisible, and the headline number it certifies stands
    unsupported.

    The list is restated here rather than read out of `state.js`: a test that
    imported the list under review could not catch it losing a member.
    """
    projection = assets["state.js"]
    for state in ROW_STATES:
        assert f".{state}" in stylesheet, (
            f"style.css paints no `.{state}` row state"
        )
        assert f'"{state}"' in projection, (
            f"state.js never computes the `{state}` flag, so the lanes that "
            f"justify its headline number are never marked"
        )


def test_every_row_state_has_a_tick_token(stylesheet):
    defined = _defined_tokens(stylesheet)
    for state in ROW_STATES:
        assert f"--panel-tick-{state}" in defined, (
            f"row state `{state}` has no --panel-tick-{state}; its colour would "
            f"have to come from somewhere outside the token block"
        )


def _colour_tokens(stylesheet):
    """Every `:root` token whose value is a hex colour, as `(r, g, b)`."""
    match = re.search(r":root\s*\{(.*?)\}", stylesheet, re.DOTALL)
    values = {}
    for found in re.finditer(r"(--[a-z0-9-]+)\s*:\s*#([0-9a-f]{6})\s*;",
                             match.group(1), re.I):
        raw = found.group(2)
        values[found.group(1)] = tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))
    return values


def _saturation(rgb):
    """HSL saturation, 0..1."""
    top, bottom = max(rgb) / 255, min(rgb) / 255
    if top == bottom:
        return 0.0
    lightness = (top + bottom) / 2
    span = top - bottom
    return span / (2 - top - bottom) if lightness > 0.5 else span / (top + bottom)


# The canvas's categorical roles: the hues that carry meaning inside the SVG.
# The panel is the instructor's dashboard, but it is still visible on a
# mirrored display, so it may spend none of these.
CANVAS_CATEGORICAL = ["--node-supply", "--node-demand"]


def test_row_state_ticks_spend_none_of_the_canvas_categorical_roles(stylesheet):
    """Tick colour is the canvas hue at LOW CHROMA, not the canvas hue.

    A relationship rather than a value, and deliberately so: the palette is
    expected to be retuned against the real projector, so a test on the numbers
    themselves would train the instructor to edit the test. `less saturated
    than every categorical role on the canvas` survives any retune that keeps
    the decision.
    """
    colours = _colour_tokens(stylesheet)
    ticks = {n: v for n, v in colours.items() if n.startswith("--panel-tick-")}
    assert ticks, "no --panel-tick-* token found -- this would pass vacuously"

    canvas = {n: colours[n] for n in CANVAS_CATEGORICAL if n in colours}
    assert canvas, f"none of {CANVAS_CATEGORICAL} is defined to compare against"
    ceiling = min(_saturation(v) for v in canvas.values())

    for name, value in sorted(ticks.items()):
        assert value not in canvas.values(), (
            f"{name} is exactly a canvas categorical hue; the panel would be "
            f"spending a role the diagram needs"
        )
        assert _saturation(value) < ceiling, (
            f"{name} is at saturation {_saturation(value):.2f}, at or above "
            f"the canvas's least-saturated categorical role ({ceiling:.2f}). "
            f"The tick is a low-chroma echo, not a second use of the hue."
        )


def test_the_ledger_carries_no_per_lane_delta_column(assets):
    """One headline pair, never a per-lane delta -- in the ledger or on the canvas.

    The two states are never simultaneously visible by design, so a per-lane
    before/after puts a number from the invisible state back on screen: the
    rejected ghost overlay re-entering through the panel's door.
    """
    for name in ("graph.js", "render.js", "index.html"):
        code = COMMENT.sub(" ", assets[name])
        assert "Δ" not in code, (
            f"{name}: contains a delta glyph outside a comment. A/B deltas are "
            f"one headline pair the instructor can say out loud, not twelve."
        )


def test_no_javascript_test_runner_is_introduced():
    """The zero-dependency posture, asserted rather than assumed.

    This is the test that has to exist for the rule at the top of this file to
    mean anything: the second install path arrives as a `package.json` nobody
    reviewed as a policy change.
    """
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    forbidden = ["package.json", "package-lock.json", "node_modules",
                 "vitest.config.js", "jest.config.js", "playwright.config.js"]
    for entry in forbidden:
        assert not os.path.exists(os.path.join(root, entry)), (
            f"{entry} exists at the repo root. The frontend is verified from "
            f"Python or not at all -- a JS toolchain here is a second way to "
            f"install this repo on the teaching laptop."
        )


# ---- the beat engine, keyboard and layer catalog (issue #41) -----------------
# Three rules land here, and each is invisible while authoring on a laptop: the
# stroke model (a dash that loses does not vanish, it becomes a dimmer solid
# line), the keyboard contract (a key that silently does nothing looks broken),
# and the illegal all-on preset.

# The documented control surface. Restated here rather than parsed out of the
# page, because this is the list the *spec* fixed -- a test that read the page's
# own key map could not catch the page dropping a key from it.
KEYS = [
    "ArrowLeft", "ArrowRight",      # one beat
    "PageDown", "PageUp",           # the same, for a presenter remote
    "ArrowUp", "ArrowDown",         # one coarse unit, landing on beat a
    "KeyZ", "KeyX", "KeyC",         # the three views, in day order
    "KeyR",                         # full view reset
]

# The beat engine's mutators. `state.js` owns them because the beat index is app
# state and that module owns app state; the keyboard driver in `index.html` may
# only call them.
BEAT_MUTATORS = ["setBeat", "stepBeat", "stepUnit", "jumpToUnit", "resetView",
                 "setSpine"]


def test_the_keyboard_reaches_every_documented_axis(assets):
    """Every key in the spec's control table is bound.

    `event.code` rather than `event.key` for the letters: `Z`/`X`/`C` were
    chosen for being bottom-row, one-handed and modifier-free, which is a fact
    about position rather than about the glyph printed on the cap.

    Scanned across both modules that own the driver. `index.html` holds the
    action table, but the three view keys are declared on the views themselves,
    so that day order -- which is also left-to-right on the keyboard -- has one
    home rather than two that can disagree about which key is Day 4.
    """
    page = COMMENT.sub(" ", assets["index.html"] + assets["views.js"])
    for key in KEYS:
        assert key in page, (
            f"index.html binds no {key}. The keyboard is the primary driver, "
            f"and a key the spec promises must not go missing mid-class."
        )
    # Digits 1-9 jump to a coarse unit. Bound as a range rather than nine
    # literals, so the assertion is on the range check rather than on nine
    # string matches a refactor would scatter.
    assert "Digit" in page, (
        "index.html binds no digit jump; `1`-`9` are the direct-jump axis"
    )


def test_the_beat_engine_lives_in_state_js(assets):
    code = COMMENT.sub(" ", assets["state.js"])
    for mutator in BEAT_MUTATORS:
        assert f"export function {mutator}" in code, (
            f"state.js exports no {mutator}. The beat index is app state, so "
            f"every mutation of it belongs to the module that owns app state."
        )


def _catalog(views_js):
    """Every layer id the catalog declares."""
    return set(re.findall(r'\{\s*id:\s*"([a-z]+)"', views_js))


def _view_layer_sets(views_js):
    """Each view's declared default layer set, as `{viewId: [layerId, ...]}`."""
    found = {}
    for block in re.finditer(
        r'id:\s*"([a-z-]+)",(?:.*?)layers:\s*\[(.*?)\]', views_js, re.DOTALL
    ):
        found[block.group(1)] = re.findall(r'"([a-z]+)"', block.group(2))
    return found


def test_layer_toggles_are_pointer_only(assets):
    """No keystroke reaches a layer toggle.

    The keyboard driver is a single `KEY_ACTIONS` table so that this is
    checkable at all: the table's actions are beat, view and reset, and never a
    layer. Layer ids are searched for by name, so adding a layer and quietly
    binding it to a key fails here.
    """
    page = COMMENT.sub(" ", assets["index.html"])
    match = re.search(r"const KEY_ACTIONS = \{(.*?)\n    \};", page, re.DOTALL)
    assert match, (
        "index.html has no `const KEY_ACTIONS = {...};` table. The keyboard's "
        "whole action set must be one readable block, or the pointer-only rule "
        "for layers cannot be checked."
    )
    table = match.group(1)
    assert "toggleLayer" not in table, (
        "a key reaches toggleLayer. Layer toggles are pointer-only: the keys "
        "stay reserved for the controls used mid-narration."
    )
    for layer in sorted(_catalog(assets["views.js"])):
        assert f'"{layer}"' not in table, (
            f"KEY_ACTIONS names the layer `{layer}`; layer toggles are "
            f"pointer-only"
        )


def test_all_layers_on_is_not_an_available_preset(assets):
    """`WORST CASE` is illegible in every colour scheme, so it is not legal.

    A view that happens to list every layer is exactly that preset arriving by
    accident, which is why this is checked rather than merely agreed.
    """
    catalog = _catalog(assets["views.js"])
    assert catalog, "views.js declares no layer catalog"
    sets = _view_layer_sets(assets["views.js"])
    assert sets, "views.js declares no view default layer sets"
    for view, layers in sets.items():
        assert set(layers) != catalog, (
            f"view `{view}` switches on the whole catalog. All-layers-on is "
            f"illegible in every scheme and is not a legal preset."
        )


def test_every_view_default_is_a_layer_the_catalog_declares(assets):
    """The catalog is global and a view is a named subset of it, never an owner.

    View-scoping was rejected because the unit's strongest moments are cross-day
    mashups -- Day 3's cut on top of Day 4's interdicted network is Day 4's
    entire punchline.
    """
    catalog = _catalog(assets["views.js"])
    for view, layers in _view_layer_sets(assets["views.js"]).items():
        unknown = sorted(set(layers) - catalog)
        assert not unknown, f"view `{view}` defaults to unknown layer(s) {unknown}"


def test_every_layer_has_a_root_class_rule(assets, stylesheet):
    """A layer is a root class, so switching a view on is a set of class names.

    A layer with no rule is a toggle that shows nothing -- a button in the
    catalog that has never done anything, discovered by pressing it in class.
    """
    for layer in sorted(_catalog(assets["views.js"])):
        assert f".show-{layer}" in stylesheet, (
            f"layer `{layer}` has no `.show-{layer}` rule in style.css; its "
            f"toggle would switch on nothing"
        )


def test_no_transition_on_a_state_carrying_property(stylesheet):
    """Nothing animates, anywhere.

    Motion during a sentence steals the room from the instructor's voice, and
    fast stepping must degrade into a legible flip-book rather than a queue of
    overlapping animations. A blanket ban rather than a per-property one:
    every appearance value in this file is state-carrying by construction,
    since the whole page is a class change followed by a repaint.
    """
    code = COMMENT.sub(" ", stylesheet)
    for banned in ("transition", "animation", "@keyframes"):
        assert banned not in code, (
            f"style.css declares `{banned}`. No CSS transition on any "
            f"state-carrying property: a transition mid-sentence competes with "
            f"the instructor's voice, and fast stepping would overlap them."
        )


# ---- the stroke model -------------------------------------------------------
# Two halves of one model: pitch (does the pattern still read as broken?) and
# presence (is the mark there at all?). Both are arithmetic over authored values
# with no DOM, which is what lets them live under this file's Python-or-nothing
# rule -- exactly like the crossing-angle floor in `layout_geometry.py`.
#
# The room: a 2.5 m image on a 1060-unit viewBox at 8 m, so ONE VIEWBOX UNIT IS
# ONE ARCMINUTE and stroke widths read as angles with no conversion.
MODULATION_FLOOR = 0.5182   # Michelson depth a smeared pattern must keep
MAR = 1.97                  # 1 minimum angle of resolution at the 20/40 design
                            # observer, in viewBox units. Confirmed with the
                            # instructor; the room, not the eye chart, is what
                            # this is retuned against.
MIN_LANE = 120              # the shortest lane that may carry a mark
MIN_CYCLES = 3              # fewer reads as an accident of where the lane ended
DUTY_CAP = 0.6              # above this the closed form runs away; see below
DASHED_W_FLOOR = 3.16       # minimum stroke weight for any dashed mark, in
                            # viewBox units. A recorded value rather than a
                            # derived one, and the test below is what keeps the
                            # two honest with each other.

# Marks allowed to fail the PRESENCE floor, and why. Both are on record so the
# question is not reopened a third time: neither is a mark the back row is meant
# to read, and both carry their meaning somewhere other than the stroke.
FADE_ALLOWED = {
    "--synth": "derived machinery, declared front-of-room; scaffolding may fade",
    "--removed": "removal's meaning is on the X glyph, not on the stroke",
}


def _pitch_floor(duty, smear):
    """The shortest dash pitch whose smeared modulation still clears the floor.

    Closed form, not a table. Keep the fundamental of the square wave: mean
    coverage is the duty cycle *d*, the fundamental's amplitude is
    `(2/pi)sin(pi d)`, and a Gaussian's MTF at period *p* is
    `exp(-2 pi^2 sigma^2 / p^2)`. Set the depth to the floor and solve.

    Accurate to ~1% up to duty 0.6 against a numeric sweep, then it runs away,
    and above duty ~0.65 it has NO SOLUTION at all -- which is the useful half:
    above that a square wave's trough is held open by its harmonics, and
    harmonics are the first thing a blur removes.

    **Exactly independent of stroke weight.** A dashed stroke is a union of
    rectangles and a Gaussian is separable, so blurred coverage factorises into
    an along-stroke term and an across-stroke one; the across term is constant
    along the stroke, multiplies peak and trough alike, and cancels out of the
    ratio identically. Weight decides whether the mark is present, not whether
    it is dashed -- which is why there are two floors here and not one.
    """
    ratio = (2 / math.pi) * math.sin(math.pi * duty) / (MODULATION_FLOOR * duty)
    if ratio <= 1:
        return math.inf     # no pitch survives at this duty
    return math.pi * smear * math.sqrt(2 / math.log(ratio))


def _dash_patterns(stylesheet):
    """Every declared dash pattern, as `{prefix: (dash, gap)}`.

    Keyed by the token's prefix so a pattern can be paired with the weight and
    opacity tokens sharing it -- `--residual-dash` with `--residual-w`. That
    naming rule is what makes both floors checkable at all, and
    `test_every_dash_pattern_pairs_with_a_stroke_weight` asserts it directly.
    """
    match = re.search(r":root\s*\{(.*?)\}", stylesheet, re.DOTALL)
    found = {}
    for token in re.finditer(
        r"(--[a-z0-9-]+)-dash\s*:\s*([\d.]+)\s+([\d.]+)\s*;", match.group(1)
    ):
        found[token.group(1)] = (float(token.group(2)), float(token.group(3)))
    assert found, "no dash pattern found in :root -- this would pass vacuously"
    return found


@pytest.fixture(scope="module")
def smear(stylesheet):
    """The back-row smear: ONE authored quantity the whole model derives from.

    A safety margin rather than a measurement -- it corresponds to roughly a
    20/204 observer, about ten times a 20/20 eye. If the real room differs from
    the model, this is the number that changes, and every clearance below
    re-derives from it. That is the entire reason it is one token.
    """
    value = _numeric_tokens(stylesheet).get("--smear")
    assert value, (
        "style.css defines no --smear. The stroke model is one authored "
        "quantity plus a derivation per pattern; without the quantity, every "
        "derived value is a magic number nobody can retune against the room."
    )
    return value


def test_every_dash_pattern_pairs_with_a_stroke_weight(stylesheet):
    numeric = _numeric_tokens(stylesheet)
    for prefix in sorted(_dash_patterns(stylesheet)):
        assert f"{prefix}-w" in numeric, (
            f"{prefix}-dash has no {prefix}-w. Presence is `weight x duty x "
            f"opacity`, so a pattern whose weight cannot be found by name is a "
            f"pattern neither floor can be applied to."
        )


def test_every_dash_pattern_is_authored_under_the_duty_cap(stylesheet):
    for prefix, (dash, gap) in sorted(_dash_patterns(stylesheet).items()):
        duty = dash / (dash + gap)
        assert duty <= DUTY_CAP, (
            f"{prefix}-dash is `{dash} {gap}`, duty {duty:.2f}, over the "
            f"{DUTY_CAP} authoring cap. Above it a pattern's trough is held "
            f"open by its harmonics -- the first thing a blur removes -- so it "
            f"survives for a reason that does not survive the room."
        )


def test_every_dash_pattern_clears_the_pitch_floor(stylesheet, smear):
    """A dash that loses does not vanish -- it becomes a dimmer solid line.

    That failure mode is the whole argument for checking this from a test: the
    mark is still there, still the right colour, and saying the wrong thing.
    """
    for prefix, (dash, gap) in sorted(_dash_patterns(stylesheet).items()):
        pitch = dash + gap
        floor = _pitch_floor(dash / pitch, smear)
        assert pitch >= floor, (
            f"{prefix}-dash has pitch {pitch} against a floor of {floor:.1f} at "
            f"smear {smear}. It will read as a solid line from the back row."
        )


def test_every_dash_pattern_shows_at_least_three_cycles(stylesheet):
    """Fewer than three cycles reads as an accident of where the lane ended
    rather than as a pattern, which spends the register without buying it."""
    ceiling = MIN_LANE / MIN_CYCLES
    for prefix, (dash, gap) in sorted(_dash_patterns(stylesheet).items()):
        assert dash + gap <= ceiling, (
            f"{prefix}-dash has pitch {dash + gap}, over the {ceiling:.0f} that "
            f"fits {MIN_CYCLES} cycles on the shortest lane a mark may sit on "
            f"({MIN_LANE} units)"
        )


def test_the_dashed_stroke_floor_is_what_the_two_constraints_imply(smear):
    """3.16 units is derived here rather than restated.

    The pitch floor and the three-cycle ceiling together cap the duty cycle; the
    presence floor then divides through that cap. Pinning the derivation instead
    of the number means a retune of the smear moves the floor, rather than
    leaving 3.16 behind as a constant nobody can re-justify.

    The two checks are asymmetric on purpose. The duty cap is compared loosely,
    because the closed form is a ~1% approximation and pinning it tighter than
    its own accuracy would be pinning noise. The stroke floor is compared with a
    DIRECTION: the shipped 3.16 must be at least what the model implies -- a
    recorded constant that is a shade conservative is a rounding, while one that
    is a shade generous is a mark authored under the floor with a test agreeing.
    """
    ceiling = MIN_LANE / MIN_CYCLES
    duty = max(step / 1000 for step in range(1, 651)
               if _pitch_floor(step / 1000, smear) <= ceiling)
    assert abs(duty - 0.625) < 0.01, (
        f"the pitch rule and the three-cycle ceiling now cap duty at {duty:.3f}, "
        f"not the 0.625 on record -- further apart than the closed form's own "
        f"~1% accuracy explains, so something in the model has moved"
    )
    implied = MAR / duty
    assert implied <= DASHED_W_FLOOR, (
        f"the model now implies a dashed-stroke floor of {implied:.2f}, above "
        f"the {DASHED_W_FLOOR} on record. Marks authored at the recorded floor "
        f"are under the real one."
    )
    assert DASHED_W_FLOOR - implied < 0.05, (
        f"{DASHED_W_FLOOR} is {DASHED_W_FLOOR - implied:.2f} above the "
        f"{implied:.2f} the model implies -- no longer a rounding, so the "
        f"recorded floor has come adrift from its derivation"
    )


def test_every_dashed_mark_clears_the_presence_floor(stylesheet, smear):
    """Effective width = weight x duty x opacity, and it must clear 1 MAR.

    The angular floor and the ink floor collapse together once a smeared dash is
    recognised as a solid line of its own mean luminance -- so there is one
    number here rather than two.
    """
    numeric = _numeric_tokens(stylesheet)
    for prefix, (dash, gap) in sorted(_dash_patterns(stylesheet).items()):
        duty = dash / (dash + gap)
        effective = numeric[f"{prefix}-w"] * duty * numeric.get(f"{prefix}-op", 1.0)
        if prefix in FADE_ALLOWED:
            # Recorded, not silently skipped. A mark intended to recede failing
            # a presence floor is the criterion agreeing with the design -- and
            # an exemption that stops being needed should come off the list
            # rather than sit here unexamined.
            assert effective < MAR, (
                f"{prefix} is on the fade list ({FADE_ALLOWED[prefix]}) but now "
                f"clears the presence floor at {effective:.2f}. Either the token "
                f"moved or the exemption is stale -- take it off the list."
            )
            continue
        assert effective >= MAR, (
            f"{prefix} has effective width {effective:.2f} against the {MAR} "
            f"floor at the 20/40 design observer. It is a dashed mark thinner "
            f"than the room can resolve, so it reads as an absence."
        )


def test_the_fade_list_is_closed(stylesheet):
    """Only the two marks on record may fade, and they must still exist."""
    patterns = _dash_patterns(stylesheet)
    for prefix in FADE_ALLOWED:
        assert prefix in patterns, (
            f"{prefix} carries no dash pattern any more, so its fade exemption "
            f"is stale and should be removed rather than left standing"
        )


# ---- the scaffold tier ------------------------------------------------------
def test_the_scaffold_tier_owns_opacity_alone(stylesheet):
    """Dimming is one tier's channel, and nothing else may use it.

    Lanes the active annotation does not touch dim to the scaffold tier, which
    is only safe because an empty hot set means *every* lane is hot -- so the
    graph is never dimmed when it is itself the subject. If a second mechanism
    also dimmed, the two would compose into a lane at 9% nobody authored.
    """
    assert "--scaffold-op" in _defined_tokens(stylesheet), (
        "no --scaffold-op token; the scaffold tier's dimming would be a "
        "hard-coded opacity outside the block that retunes the diagram"
    )
    code = COMMENT.sub(" ", stylesheet)
    for rule in re.finditer(r"([^{}]*)\{([^{}]*)\}", code):
        selector, body = rule.group(1), rule.group(2)
        if "var(--scaffold-op)" in body:
            assert ".cold" in selector, (
                f"`{selector.strip()}` dims with the scaffold opacity but is "
                f"not a `.cold` rule. The scaffold tier owns opacity."
            )


def test_an_empty_hot_set_means_every_lane_is_hot(assets):
    """The rule that makes the scaffold tier safe, asserted where it lives.

    Without it, the pristine opening screen -- the one picture whose subject is
    the graph itself -- would render with every lane dimmed to 30%.
    """
    code = COMMENT.sub(" ", assets["state.js"])
    assert "export function anyHot" in code, (
        "state.js exports no `anyHot`. Whether anything is hot at all is the "
        "single question the scaffold tier turns on, and it must be answered in "
        "one place or the canvas and the ledger will answer it differently."
    )
    assert "cold" in code, (
        "state.js never computes coldness, so nothing decides which lanes the "
        "scaffold tier dims"
    )
