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
    "KeyD", "KeyT",                 # the two cycling axes (issue #45)
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


def test_every_dashed_mark_clears_the_recorded_stroke_floor(stylesheet):
    """`w >= 3.16` for any dashed mark, stated as flatly as the spec states it.

    Nearly but not quite the presence floor above: that one divides through each
    pattern's own duty cycle, where this is the single number an author can
    check a new mark against without doing any arithmetic. Both are here because
    the flat one is the rule people will actually apply, and it should fail on
    the same marks the derived one fails on rather than being a second opinion.

    Same exemption list, for the same recorded reasons. A mark that is allowed
    to be too faint to read is allowed to be too thin to carry a dash.
    """
    numeric = _numeric_tokens(stylesheet)
    for prefix in sorted(_dash_patterns(stylesheet)):
        weight = numeric[f"{prefix}-w"]
        if prefix in FADE_ALLOWED:
            assert weight < DASHED_W_FLOOR, (
                f"{prefix} is on the fade list ({FADE_ALLOWED[prefix]}) but is "
                f"now {weight} units, at or over the {DASHED_W_FLOOR} floor -- "
                f"the exemption is stale, take it off the list"
            )
            continue
        assert weight >= DASHED_W_FLOOR, (
            f"{prefix} is a dashed mark at {weight} units, under the "
            f"{DASHED_W_FLOOR} floor. Below it there is no duty cycle that "
            f"satisfies pitch and presence at once, so the pattern cannot be "
            f"rescued by re-pitching it -- the stroke has to get heavier."
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


# ---- the Flow & Cut view (issue #42) ----------------------------------------
# Days 2 and 3 on one screen, because the min cut is a certificate *of the flow
# just computed* and re-rendering it fresh severs the argument. What is checked
# here is what a laptop cannot show: the reverse arc's geometry, the promotion
# rule that keeps two arcs from merging, and the standing ban on solver
# arithmetic in JavaScript.

# The two offsets the residual marks live at, and the reason there are two.
# Authored in `render.js` as named constants rather than inline, because the
# 11/22 relationship is the whole of why promotion must REPLACE rather than add.
RESIDUAL_OFFSET = 11
REVERSE_OFFSET = 22


def _js_constant(text, name):
    """A `const NAME = <number>;` declaration's value, or None."""
    found = re.search(rf"const {name}\s*=\s*(-?[\d.]+)\s*;", text)
    return float(found.group(1)) if found else None


def test_the_two_residual_offsets_are_named_constants(assets):
    """The offsets are the geometry the promotion rule is derived from.

    Inline, they are two magic numbers eleven apart; named, the relationship
    between them is legible to whoever next changes one.
    """
    render = assets["render.js"]
    for name, expected in (("RESIDUAL_OFFSET", RESIDUAL_OFFSET),
                           ("REVERSE_OFFSET", REVERSE_OFFSET)):
        assert _js_constant(render, name) == expected, (
            f"render.js declares no `const {name} = {expected};`. The reverse "
            f"arc is promoted in place at offset {REVERSE_OFFSET} while the "
            f"plain residual arc sits at {RESIDUAL_OFFSET}."
        )


def test_the_promoted_reverse_arc_spends_no_hue(assets, stylesheet):
    """Three non-colour channels and no hue, because colour was not available.

    Path-vs-lane is dE 66 normally and 3.1 under achromatopsia, so the reverse
    arc is distinguished by offset, by its hollow head and by suppressing the
    plain arc -- never by being a different colour from the residual arc it is
    a promotion of.
    """
    rule = re.search(r"\.reverse-arc\s*\{([^}]*)\}", stylesheet)
    assert rule, (
        "style.css paints no `.reverse-arc`. A residual arc traversed against "
        "its lane is promoted in place, and the promotion needs a rule."
    )
    body = rule.group(1)
    for token in ("--residual", "--residual-w", "--residual-dash"):
        assert token in body, (
            f"`.reverse-arc` does not reach for {token}. The promoted arc is "
            f"the residual arc moved and re-headed -- stroke 4, dash 22 18 -- "
            f"so it must share the tokens rather than restate the values."
        )
    # `--cut`, `--path` and the node roles are the hues that carry meaning.
    for hue in ("--cut", "--path", "--node-supply", "--node-demand", "--lane-hot"):
        assert hue not in body, (
            f"`.reverse-arc` spends {hue}. The mark spends three non-colour "
            f"channels and no hue; a second hue here is one the room cannot "
            f"tell from the first under achromatopsia."
        )


def test_the_promoted_arc_has_a_hollow_head_of_its_own(assets, stylesheet):
    """A hollow head is the glyph channel, and it needs a second marker.

    Reusing `#arrowhead` would leave the promotion carrying two channels where
    the design spends three, and the head is the one that survives being
    printed in greyscale.
    """
    assert 'id="arrowhead-hollow"' in assets["index.html"], (
        "index.html defines no `arrowhead-hollow` marker; the promoted reverse "
        "arc has no hollow head to wear"
    )
    assert "arrowhead-hollow" in stylesheet, (
        "nothing in style.css attaches the hollow head to a mark, so the "
        "marker is defined and never worn"
    )


def test_promotion_replaces_the_plain_arc_rather_than_adding_to_it(assets):
    """Two arcs at 11 and 22 sit 4.0 units apart and merge into one thick mark.

    A trap only drawing reveals, and the reason the suppression is a rule
    rather than a preference: the merged pair reads as a single heavy arc that
    says neither thing.
    """
    code = COMMENT.sub(" ", assets["render.js"])
    assert "promoted" in code, (
        "render.js never mentions promotion, so nothing suppresses the plain "
        "residual arc of a lane whose reverse arc is promoted"
    )


def test_an_offset_chord_is_clipped_by_circle_intersection(assets):
    """An offset chord's endpoints float clear of the node rim.

    The usual trim walks in along the centre line, which is the wrong line for
    a mark that is not on it -- the arc ends short of the disc on one side and
    inside it on the other. Only drawing reveals this, so it is pinned here.
    """
    code = COMMENT.sub(" ", assets["render.js"])
    assert "circleIntersection" in code, (
        "render.js has no `circleIntersection`. An offset arc trimmed by the "
        "centre-line rule does not meet the node rim it is drawn between."
    )


def test_the_min_cut_lane_adopts_the_recorded_dash(stylesheet):
    """`16 24` -- the one subject mark that had no value on record."""
    assert _dash_patterns(stylesheet)["--cut"] == (16.0, 24.0), (
        "the min-cut lane's dash is no longer `16 24`, the pattern recorded "
        "for it when it was the one subject mark with no value on file"
    )


def test_the_cut_is_drawn_as_a_partition_and_not_a_lane_list(assets, stylesheet):
    """S-side and T-side shading, so the certificate is a partition.

    A list of lane names is a list; the shading is what makes the min cut read
    as the S-T partition it is defined to be.
    """
    for side in ("s-side", "t-side"):
        assert f".{side}" in stylesheet, (
            f"style.css paints no `.{side}`; the cut would render as a set of "
            f"marked lanes with no partition behind it"
        )
    # Read in `state.js` rather than in the render pass: which side of the cut
    # a node is on is app state off the `/maxflow` response, and the render
    # pass only ever projects state onto classes.
    code = COMMENT.sub(" ", assets["state.js"])
    assert "source_side" in code, (
        "state.js never reads `source_side`, so nothing decides which side of "
        "the cut a node is on"
    )


def test_the_direction_glyph_is_scoped_to_a_traversal_against_the_lane(stylesheet):
    """A forward traversal is unmarked, and the glyph is a stylesheet rule.

    One lane, one row, one numeral, one glyph -- so the glyph is `content` on
    an existing cell rather than a second row, a second column or a per-
    direction split of the ledger.
    """
    rule = re.search(r"#ledger tr\.on-path\.against[^{]*\{([^}]*)\}", stylesheet)
    assert rule, (
        "style.css has no `#ledger tr.on-path.against` rule. The direction "
        "glyph belongs to rows that are BOTH on the path and running against "
        "the lane; scoped any wider it marks forward traversals too."
    )
    assert "content:" in rule.group(1), (
        "the against-rule paints no `content`; the glyph is drawn by the "
        "stylesheet so that no second element has to exist for it"
    )


def test_the_beat_timeline_is_populated_and_its_rows_reach_a_beat(assets):
    """The timeline is a slot the view fills, and clicking a row is a jump.

    A pointer action may only duplicate a keyboard jump, which is exactly what
    this is: every row is reachable by a digit or by stepping.
    """
    page = COMMENT.sub(" ", assets["index.html"])
    assert 'id="timeline"' in page, "index.html has no timeline slot"
    assert "setBeat" in page, (
        "nothing in index.html reaches `setBeat`, so a timeline row click "
        "cannot land on the beat it names"
    )
    assert "buildTimeline" in COMMENT.sub(" ", assets["graph.js"]), (
        "graph.js does not build the timeline. The render pass never appends "
        "an element, so the rows have to be emitted by the module that owns "
        "structure."
    )


# Field names from the /maxflow trace payload. Their presence in the JS is what
# says the numbers were READ rather than recomputed -- the one rule this view
# cannot be allowed to break, because a residual the API disagrees with is a
# number on the projector that contradicts an answer the same tool gave a
# minute earlier.
#
# `used_reverse` is deliberately NOT on this list. Every arc it names is an arc
# of the same step's path, so reading it would mark nothing the path has not
# already marked -- and what drives the promotion is the drawn lane's own
# direction, which is a fact about the picture rather than about the solver's
# bookkeeping.
TRACE_FIELDS = ["lane_residuals", "bottleneck", "total_after",
                "forward_residual", "reverse_residual", "flows"]


def test_every_number_the_view_draws_comes_off_the_trace(assets):
    code = " ".join(COMMENT.sub(" ", assets[name])
                    for name in ("state.js", "render.js", "index.html"))
    for field in TRACE_FIELDS:
        assert field in code, (
            f"no module reads `{field}` off the trace. Every number this view "
            f"draws is server-computed; one that is not is one the API can "
            f"disagree with, mid-class, with nothing raised anywhere."
        )


def test_no_module_derives_a_residual_or_a_flow_in_javascript(assets):
    """No solver arithmetic in JavaScript, ever.

    `cap - flow` is the tempting one: it is one line, it is correct on the
    happy path, and it silently disagrees with the server the moment a threat
    picture, a removal or a rounding rule moves underneath it. The server ships
    `flows` and both residual lists precisely so this subtraction never has to
    be written.
    """
    banned = re.compile(r"\b(cap|capacity)\s*-\s*(flow|residual)\b", re.I)
    for name, text in assets.items():
        if not name.endswith((".js", ".html")):
            continue
        code = COMMENT.sub(" ", text)
        found = banned.search(code)
        assert not found, (
            f"{name}: computes {found.group(0)!r}. Residuals and per-edge "
            f"flows are computed server-side and shipped; deriving either here "
            f"is the divergence the trace payload exists to prevent."
        )


# ---- the Interdiction view (issue #43) --------------------------------------
# Day 4, the adversary's turn. Two things are checked here that a laptop cannot
# show: that nothing about how long Day 4 is is decided in JavaScript, and that
# carrying two tracks up the ladder spends no second visual channel.

# Field names from the /interdict ladder payload. Their presence in the JS is
# what says the ladder's shape was READ rather than worked out here. Ladder
# length, rung collapse and divergence are server facts: a frontend that decided
# any of them would be a second implementation of the stop rule, disagreeing with
# the CLI on the one dataset nobody checked.
#
# `baseline_throughput` is deliberately NOT on this list. The ladder carries it
# and the view does not draw it: the untouched theater's throughput sits one
# slot from the cut capacity it must equal by max-flow/min-cut, so both come off
# the one `/maxflow` response instead. The only ladder numbers that reach the
# screen are the ones no other response also computes.
LADDER_FIELDS = ["rungs", "k_through", "terminated", "residual_throughput",
                 "diverges", "exhaustive", "greedy", "searched", "skipped"]


def test_the_whole_ladder_is_fetched_in_one_request(assets):
    """One call per dataset, and it is api.js that knows the parameter.

    Stepping never awaits a fetch, so the alternative to one ladder call is the
    2 x K x datasets requests a per-rung frontend would issue -- each of them a
    request that can fail while the room watches.
    """
    api = COMMENT.sub(" ", assets["api.js"])
    assert "export function fetchLadder" in api, (
        "api.js exports no `fetchLadder`. Every fetch and every endpoint path "
        "belongs to api.js, and Day 4's ladder is a fetch."
    )
    assert "ladder" in api, (
        "api.js never asks for `ladder=true`, so /interdict would answer in its "
        "single-k shape and Day 4 would have one rung"
    )


def test_the_ladder_is_installed_as_one_complete_spine(assets):
    """A spine is installed complete or not at all.

    Half a ladder is a keyboard that works for three presses and then declines
    silently, which is the one failure worse than a key that is not yet bound.
    """
    page = COMMENT.sub(" ", assets["index.html"])
    assert "fetchLadder" in page, "index.html never fetches the ladder"
    assert "interdictionSpine" in page, (
        "index.html never builds the interdiction spine, so the view falls back "
        "to the one-beat entry spine and every Day 4 key is a no-op"
    )
    assert re.search(r'setSpine\(\s*"interdiction"', page), (
        "nothing installs a spine under the `interdiction` view id"
    )
    # The keyboard goes live last, once the spines are installed. Asserted by
    # position rather than by presence: bound earlier, the arrows are answerable
    # during the fetch and land on the fallback spine.
    assert page.index("fetchLadder") < page.index("bindKeys()"), (
        "the keyboard is bound before the ladder is in hand"
    )


def test_the_shape_of_day_four_comes_off_the_payload(assets):
    """Ladder length, rung collapse and divergence are server facts.

    Nothing about how long Day 4 is may be decided in JavaScript. The field
    names are the evidence: a spine built by reading `rungs` and `diverges` is a
    spine the server's own tests already pinned.
    """
    code = " ".join(COMMENT.sub(" ", assets[name])
                    for name in ("state.js", "render.js", "graph.js", "index.html"))
    for field in LADDER_FIELDS:
        assert field in code, (
            f"no module reads `{field}` off the ladder payload. Day 4's length, "
            f"its collapsed rungs and its divergences are computed once on the "
            f"server so that a test can pin them."
        )


def test_the_timeline_flags_a_diverging_rung(assets, stylesheet):
    """"k=1 agrees, k=2 and k=3 do not", visible without stepping the ladder.

    The flag is a class on the row the spine already emits and a stylesheet
    `content` -- the same channel the direction glyph uses, for the same reason:
    one row, one glyph, and no second element the render pass has to keep in
    step.
    """
    assert "diverges" in COMMENT.sub(" ", assets["graph.js"]), (
        "graph.js writes no divergence class onto a timeline row, so a rung "
        "where greedy is wrong looks exactly like one where it is not"
    )
    rule = re.search(r"#timeline \.beat-row\.diverges[^{]*\{([^}]*)\}", stylesheet)
    assert rule, (
        "style.css has no `#timeline .beat-row.diverges` rule; the flag would "
        "be a class that paints nothing"
    )
    assert "content:" in rule.group(1), (
        "the divergence flag paints no `content`; it is drawn by the stylesheet "
        "so that no second element has to exist for it"
    )


def test_the_search_counts_are_labelled_searched_and_skipped(assets):
    """Two labelled numbers, never one number beside a greedy result.

    `subsets_total` on a greedy track is a false claim about work greedy never
    did, and the counts are the Day 4 number -- how fast the space grows -- so
    they are labelled rather than left to be inferred from position.
    """
    graph = COMMENT.sub(" ", assets["graph.js"])
    for slot in ("searched", "skipped"):
        assert re.search(rf'id:\s*"{slot}"', graph), (
            f"graph.js declares no `{slot}` headline slot"
        )
        assert re.search(rf'label:\s*"{slot}"', graph, re.I), (
            f"the `{slot}` slot is not labelled `{slot}`; an unlabelled count "
            f"beside a result is read as a claim about that result"
        )


def test_both_tracks_reach_the_headline_as_a_pair(assets):
    """`140 / 140` -- agreement STATED, not absent.

    A rung with one track on screen is the failure the whole two-track ladder
    exists to prevent: a student reads the blank half as "greedy wasn't run",
    and the theater's greedy correctness stops being a theorem about the
    network's shape and starts looking like luck.
    """
    graph = COMMENT.sub(" ", assets["graph.js"])
    assert re.search(r'id:\s*"tracks"', graph), (
        "graph.js declares no `tracks` headline slot, so the two tracks' "
        "residuals have nowhere fixed to be read side by side"
    )
    state = COMMENT.sub(" ", assets["state.js"])
    assert "greedy" in state and "exhaustive" in state, (
        "state.js reads only one track off a rung; both render on every "
        "dataset, including the ones where they agree"
    )


def test_the_interdicted_subset_is_a_row_state_and_not_a_second_list(assets):
    """The blockade is `.removed` rows on the one ledger, with a count above.

    A separate list puts the same lane in the panel twice, in two renderings
    that can disagree -- and the headline count is read off the very flags that
    class the rows, so the number and its certificate cannot come apart.
    """
    state = COMMENT.sub(" ", assets["state.js"])
    removed = re.search(r'"removed":\s*([^\n]*)', state)
    assert removed, "state.js no longer computes a `removed` row state"
    assert "struck" in removed.group(1), (
        "the `removed` row state does not include the beat's blockade, so an "
        "interdicted lane would be drawn only where a THREAT PICTURE removed it"
    )
    assert "struck" in re.search(r"marks:\s*\{(.*?)\n  \}", state, re.DOTALL).group(1), (
        "state.js has no `struck` set in `marks`. The interdicted subset is a "
        "subset of the lanes, so it lives with the other lane subsets."
    )


def test_carrying_two_tracks_spends_no_new_channel(assets, stylesheet):
    """No hue, glyph, dash or weight is spent by having two tracks.

    Only one blockade is ever drawn, so `.removed` stays a single row state and
    the `X` keeps its one meaning. "Attacked" is carried by the A/B flip --
    the transition is the verb -- because a distinct hue for it costs a role the
    palette cannot afford.
    """
    defined = _defined_tokens(stylesheet)
    for token in sorted(defined):
        for banned in ("greedy", "exhaustive", "attack", "interdict", "blockade"):
            assert banned not in token, (
                f"{token} spends a channel on Day 4's second track. Only one "
                f"blockade is ever drawn; the other is stated as a number."
            )
    # `.removed` stays ONE row state, so the `X` glyph keeps its one meaning.
    # Read out of `state.js` and compared against the list this file restates,
    # because the question is whether the APPLICATION grew a sixth state -- a
    # comparison against another constant in this file could never answer it.
    declared = re.search(r"export const ROW_STATES = \[(.*?)\]",
                         assets["state.js"], re.DOTALL)
    assert declared, "state.js no longer declares ROW_STATES"
    assert set(re.findall(r'"([a-z-]+)"', declared.group(1))) == set(ROW_STATES), (
        "the application's row-state list no longer matches the five this file "
        "names. Day 4 carries two tracks and must add none: only one blockade "
        "is ever drawn, and the other track is stated as a number."
    )


def test_the_min_cut_is_on_screen_from_beat_zero(assets):
    """A budgeted adversary rediscovering the cut is recognition, not a reveal.

    Both halves of the cross-day mashup are the view's entry state, which is
    also the strongest moment in the unit: Day 3's cut layered over Day 4's
    interdicted network.
    """
    layers = _view_layer_sets(assets["views.js"])["interdiction"]
    for layer in ("cut", "removed"):
        assert layer in layers, (
            f"the interdiction view does not enter with `{layer}` on"
        )
    state = COMMENT.sub(" ", assets["state.js"])
    spine = re.search(r"export function interdictionSpine\b(.*)", state, re.DOTALL)
    assert spine, "state.js exports no `interdictionSpine`"
    assert "showCut" in spine.group(1), (
        "the interdiction spine never draws the cut, so a budgeted adversary "
        "rediscovering it would read as a surprise reveal rather than as "
        "recognition"
    )
    # And it is the SAME `showCut` the Flow & Cut spine uses. Day 4 draws Day
    # 3's certificate underneath its own wreckage, and a certificate rendered
    # from two blocks of code is one that can mean one thing on Wednesday and
    # another on Thursday.
    shared = re.search(r"function showCut\b(.*?)\n\}", state, re.DOTALL)
    assert shared, "state.js has no shared `showCut`"
    for field in ("cut_lanes", "source_side", "cut_capacity"):
        assert field in shared.group(1), (
            f"`showCut` never reads `{field}`, so the certificate on screen is "
            f"not the one the server computed"
        )
    assert len(re.findall(r"showCut\(", state)) >= 3, (
        "`showCut` is declared and called once; both spines that show a cut "
        "must go through it"
    )


# ---- the Cost & Risk view (issue #44) ---------------------------------------
# Day 1, and the lambda sequel folded into it. What is checked here is what a
# laptop cannot show: that the coarse unit is a distinct Pareto POINT rather
# than a lambda value, that the two failures of the naive plan stay two
# structurally different things, and that the degenerate view x dataset
# combination is labelled rather than struck.

# The three node states this view introduces, and the only list of them in this
# file. Restated here rather than imported out of `state.js` for the same reason
# `ROW_STATES` is: a test that read the list under review could not catch it
# losing a member.
NODE_STATES = ["overdrawn", "unreachable", "illegal"]

# The sentence the degenerate combination puts in the headline. Asserted
# verbatim because it is what the room reads instead of a punchline, and an
# implementer who reworded it to something vaguer would be quietly turning a
# labelled combination back into a mute one.
DEGENERATE_NOTE = "no risk data; frontier is a single point"


def test_both_arrays_are_prefetched_before_the_first_keypress(assets):
    """/sweep and /naive, in hand before the dial can be turned.

    The dial never awaits a fetch. Both arrays are the same length and in the
    same lambda order by the API's own contract, so the A/B flip is a swap at
    one index -- and a flip that awaited anything could not be stepped
    backwards at speaking pace.
    """
    api = COMMENT.sub(" ", assets["api.js"])
    for fetcher in ("fetchSweep", "fetchNaive"):
        assert f"export function {fetcher}" in api, (
            f"api.js exports no `{fetcher}`. Every fetch and every endpoint "
            f"path belongs to api.js, and Day 1 needs both arrays."
        )

    page = COMMENT.sub(" ", assets["index.html"])
    for fetcher in ("fetchSweep", "fetchNaive"):
        assert fetcher in page, f"index.html never calls {fetcher}"
        assert page.index(fetcher) < page.index("bindKeys()"), (
            f"{fetcher} is called after the keyboard goes live, so the first "
            f"press could land on a spine that is not yet installed"
        )
    assert re.search(r'setSpine\(\s*"cost-risk"', page), (
        "nothing installs a spine under the `cost-risk` view id, so Day 1 "
        "falls back to the one-beat entry spine and every key is a no-op"
    )


def test_the_coarse_unit_is_a_pareto_point_and_dedup_is_on_the_pair(assets):
    """Four detents, not eight lambdas -- and a block collapses only if NEITHER
    side moved.

    Walking lambda positions would make the first four presses of Day 1 change
    nothing on screen, which is the exact dead-key failure the beat model
    exists to prevent, sitting in the default sweep at the worst possible
    moment. Dedup on the optimum alone would be the same bug one step later: on
    the theater the naive plan moves at a lambda where the optimum does not.
    """
    state = COMMENT.sub(" ", assets["state.js"])
    assert "export function paretoRows" in state, (
        "state.js exports no `paretoRows`. The dedup has exactly one "
        "implementation, because the panel's rows and the spine's detents are "
        "the same decision -- computed twice, they can disagree."
    )
    block = re.search(r"export function paretoRows\b(.*?)\n\}", state, re.DOTALL)
    assert block, "`paretoRows` is not a single readable function"
    body = block.group(1)
    # Both sides of the pair have to be keyed, or the collapse is on one plan.
    assert "legs" in body, (
        "`paretoRows` never keys the optimum on its `legs`, so two different "
        "optimal plans could collapse into one detent"
    )
    assert "convoys" in body, (
        "`paretoRows` never keys the naive plan on its `convoys`, so a lambda "
        "where the naive plan moves and the optimum does not would collapse -- "
        "and that lambda exists on the shipped theater"
    )
    assert "export function costRiskSpine" in state, (
        "state.js exports no `costRiskSpine`"
    )
    spine = re.search(r"export function costRiskSpine\b(.*)", state, re.DOTALL)
    assert "paretoRows" in spine.group(1), (
        "the spine does not build itself from `paretoRows`, so the detents the "
        "keyboard walks and the blocks the panel marks are two computations of "
        "the same thing"
    )


def test_the_panel_keeps_all_eight_lambda_rows(assets):
    """Eight rows, with the duplicates visible AS duplicates.

    The dedup only pays for itself as a sentence -- "the frontier has four
    points, not eight; lambda is a dial with detents" -- if the collapsed rows
    are still on screen to be pointed at. A four-row detent list would make the
    claim unprovable from the panel.
    """
    graph = COMMENT.sub(" ", assets["graph.js"])
    assert "export function buildPareto" in graph, (
        "graph.js exports no `buildPareto`. The Pareto table is a built slot "
        "like every other, and the render pass never appends."
    )
    body = re.search(r"export function buildPareto\b(.*?)\n\}", graph, re.DOTALL)
    assert body, "`buildPareto` is not a single readable function"
    assert "duplicate" in body.group(1), (
        "no row is marked as a duplicate, so the eight rows read as eight "
        "distinct plans and the detent claim cannot be made from the panel"
    )
    # The row carries its DETENT and never a beat index. A beat index here
    # would be the DOM builder working out where in the spine a detent starts
    # -- beat-engine knowledge in the module that builds elements, and wrong
    # the day the spine gains a third beat, with every click landing somewhere
    # nobody asked for and nothing raised.
    assert re.search(r"dataset\.unit\s*=", body.group(1)), (
        "a Pareto row carries no `data-unit`; neither the click target nor the "
        "active detent's contiguous block could be resolved from it"
    )
    assert not re.search(r"dataset\.beat\s*=", body.group(1)), (
        "a Pareto row carries a beat index, which means graph.js is computing "
        "where a detent starts in the spine. Addressing the unit by ordinal is "
        "the beat engine's job and `jumpToUnit` already does it."
    )


def test_the_pareto_table_carries_beat_state_and_the_timeline_is_empty(assets):
    """Three slots where the others are four, ON PURPOSE.

    A four-row detent list beside eight lambda rows would be the same
    information twice in two components that can disagree, so the beat timeline
    is empty here and the Pareto table is promoted to be the view's timeline.
    An implementer WILL be tempted to put the empty list back; the instruction
    not to is asserted along with the behaviour, because the behaviour alone
    reads as an oversight.
    """
    views = assets["views.js"]
    assert "showsTimeline" in views, (
        "views.js has no `showsTimeline`. Whether a view owns the beat "
        "timeline is a property of the view, declared beside its layer set -- "
        "not a branch buried in the page's repaint."
    )
    block = re.search(r'id:\s*"cost-risk"(.*?)\n  \},', views, re.DOTALL)
    assert block, "views.js declares no `cost-risk` view"
    assert re.search(r"timeline:\s*false", block.group(1)), (
        "the cost-risk view does not declare `timeline: false`, so the beat "
        "timeline would be populated beside the Pareto table -- the same beat "
        "state in two components that can disagree"
    )
    page = COMMENT.sub(" ", assets["index.html"])
    assert "showsTimeline" in page, (
        "index.html builds the beat timeline without asking whether this view "
        "owns it"
    )
    # The standing instruction, kept where the next implementer will read it.
    assert "Do not" in assets["views.js"], (
        "nothing records that the empty timeline slot is deliberate. Left "
        "unsaid, the next reader fixes it."
    )


def test_a_pareto_row_click_reaches_that_lambda(assets):
    """Pointer parity, and nothing more.

    A row click is a jump to that detent -- a pointer action duplicating a
    keyboard one exactly, reaching no state the keyboard cannot, which is the
    rule every pointer action on this page lives under.
    """
    page = COMMENT.sub(" ", assets["index.html"])
    binder = re.search(r"function bindPareto\(\)\s*\{(.*?)\n    \}", page, re.DOTALL)
    assert binder, (
        "index.html has no `bindPareto()`. The Pareto table is this view's "
        "timeline, and its rows are the only way a pointer reaches a detent."
    )
    assert "jumpToUnit" in binder.group(1), (
        "a Pareto row click does not reach `jumpToUnit`, so it either does "
        "nothing or resolves a detent to a beat by some second route that can "
        "disagree with the digit keys"
    )
    # And it is inert in the views whose beat state it does NOT carry. The
    # table is a fact about the dataset, so it outlives the view that reads it
    # -- but `setBeat`/`jumpToUnit` act on whatever spine is active, so an
    # ungated click in Flow & Cut would silently jump the augmentation ladder
    # to wherever detent four happens to land. No keypress in Flow & Cut means
    # "detent 4 of Day 1", and a pointer may never reach what the keyboard
    # cannot.
    assert "showsTimeline" in binder.group(1), (
        "a Pareto row click is not gated on this view owning the table's beat "
        "state, so clicking one while another view is up drives that view's "
        "spine -- a pointer reaching a state no key can"
    )
    assert "bindPareto()" in page, "bindPareto is defined but never called"


def test_the_two_violations_are_structurally_different(assets, stylesheet):
    """A too-small pipe and a bad assignment are not the same failure.

    The room has to see an ASSIGNMENT error rather than merely a lane that is
    too narrow, so the over-stock hub is a mark on the NODE and the
    over-capacity lane is a mark on the LANE. Two shapes, not two shades of one.
    """
    state = COMMENT.sub(" ", assets["state.js"])
    declared = re.search(r"export const NODE_STATES = \[(.*?)\]", state, re.DOTALL)
    assert declared, (
        "state.js declares no NODE_STATES. The node states are a closed list "
        "for the same reason the row states are: the render pass iterates it, "
        "so a fourth state is one edit plus its stylesheet rule."
    )
    assert set(re.findall(r'"([a-z-]+)"', declared.group(1))) == set(NODE_STATES), (
        f"the application's node-state list no longer matches the "
        f"{NODE_STATES} this file names"
    )
    assert "export function nodeStates" in state, (
        "state.js exports no `nodeStates`. It is the node-side twin of "
        "`laneStates`: one call classes the node and feeds the headline count, "
        "so a count and its certificate cannot come apart."
    )
    # Each state paints something, or it is a class that has never fired.
    for node_state in NODE_STATES:
        assert f".node.{node_state}" in stylesheet, (
            f"node state `{node_state}` has no `.node.{node_state}` rule in "
            f"style.css; it would be computed and never seen"
        )
    # The lane's violation stays a LANE mark, and the hub's a NODE mark.
    assert ".violation" in stylesheet, "no `.violation` lane mark rule"
    assert re.search(r"\.node\.overdrawn[^{]*\{", stylesheet), (
        "the over-stock hub paints nothing on the node itself, so it would be "
        "read as another lane problem"
    )


def test_every_supply_node_renders_including_the_idle_ones(assets):
    """An overdrawn hub beside one with spare stock makes the argument itself.

    So the healthy hubs are drawn too, with their own dispatched-against-stock
    readout -- filtering to the violating ones would leave the room looking at
    a lane problem with no allocation to compare it against.
    """
    state = COMMENT.sub(" ", assets["state.js"])
    spine = re.search(r"export function costRiskSpine\b(.*)", state, re.DOTALL)
    assert spine, "state.js exports no `costRiskSpine`"
    body = spine.group(1)
    assert "sources" in body, (
        "the spine never reads the naive plan's `sources`, which is the list "
        "carrying every supply node including the idle ones"
    )
    assert "dispatched" in body and "stock" in body, (
        "the spine carries no dispatched/stock pair, so a healthy hub would "
        "render identically to one that was never asked for anything"
    )
    # The readout is composed in the render pass from a pair on the state, the
    # same split the two-track pair already uses: state holds the numbers, the
    # render pass turns them into a string.
    render = COMMENT.sub(" ", assets["render.js"])
    assert "dispatch" in render, (
        "render.js writes no dispatched/stock readout onto the supply nodes"
    )
    # And no filter drops the healthy ones on the way through.
    assert not re.search(r"sources\s*\.\s*filter", body), (
        "the spine filters the supply nodes; every one of them renders, and "
        "the idle healthy hub is half of Day 1's argument"
    )


def test_unreachability_and_infeasibility_are_not_confused(assets, stylesheet):
    """`found: false` is why the frontend never reconciles two lists.

    The convoy count equals the demand-node count whether or not a destination
    can be reached, so an unreachable base is a convoy that failed rather than
    a missing row -- and it must not render as one that was served illegally.
    A base nothing can reach and a base served by cheating are different
    lessons.
    """
    state = COMMENT.sub(" ", assets["state.js"])
    assert "found" in state, (
        "state.js never reads a convoy's `found` flag, so an unreachable "
        "destination is indistinguishable from a served one"
    )
    # The two states paint differently, and the difference is not hue alone:
    # unreachable adopts the `removed` vocabulary -- absent rather than
    # alarming -- where illegal wears the violation hue.
    unreachable = re.search(r"\.node\.unreachable[^{]*\{([^}]*)\}", stylesheet)
    illegal = re.search(r"\.node\.illegal[^{]*\{([^}]*)\}", stylesheet)
    assert unreachable and illegal, (
        "one of the two demand-node failures has no rule of its own"
    )
    assert unreachable.group(1) != illegal.group(1), (
        "an unreachable base and an illegally-served one paint identically; "
        "unreachability and infeasibility would be read as one failure"
    )
    assert "--removed" in unreachable.group(1), (
        "the unreachable base does not reach for the `removed` vocabulary. "
        "Grey-and-struck reads as ABSENT, which is what it is; the violation "
        "hue would read as alarming, which is the other failure."
    )
    assert "--violation" in illegal.group(1), (
        "the illegally-served base does not wear the violation hue, so it "
        "would not read as part of the plan's failure"
    )


def test_the_delta_is_one_headline_pair_of_costs(assets):
    """The illegal plan looks 14% cheaper, precisely because it is cheating.

    One number the instructor can say out loud. The naive plan's notional cost
    against the feasible optimum's -- claimed on the flip, which is the view
    that owns it, because the two states are never simultaneously visible.
    """
    state = COMMENT.sub(" ", assets["state.js"])
    spine = re.search(r"export function costRiskSpine\b(.*)", state, re.DOTALL)
    body = spine.group(1)
    delta = re.search(r"\.delta\s*=\s*\{(.*?)\}", body, re.DOTALL)
    assert delta, "the cost-risk spine never claims the A/B pair"
    assert "notional_cost" in delta.group(1), (
        "the pair's `before` is not the naive plan's notional cost, which is "
        "the number carrying its own asterisk"
    )
    assert "transit_cost" in delta.group(1), (
        "the pair's `after` is not the feasible optimum's transit cost"
    )


def test_the_headline_carries_a_second_violation_count(assets):
    """Two counts, because there are two violations.

    `Over cap` counts lanes and `Over stock` counts hubs. One merged count
    would say a number the room cannot act on: it would not tell them whether
    the plan needs a bigger pipe or a different assignment.
    """
    graph = COMMENT.sub(" ", assets["graph.js"])
    assert re.search(r'id:\s*"overdrawn"', graph), (
        "graph.js declares no `overdrawn` headline slot"
    )
    render = COMMENT.sub(" ", assets["render.js"])
    assert "overdrawn" in render, (
        "nothing counts the over-stock hubs into the headline, so the second "
        "violation has a certificate on screen and no number"
    )


def test_the_naive_plan_is_read_and_never_recomputed(assets):
    """No client-side plan arithmetic, ever -- the standing ban, on Day 1.

    `over` and `overage` are properties in the core and plain fields on the
    wire precisely so that the frontend colours a lane from them. Recomputing
    `load > cap` in JavaScript is how a rounding difference puts a red lane on
    the projector that the API does not agree is red.
    """
    state = COMMENT.sub(" ", assets["state.js"])
    spine = re.search(r"export function costRiskSpine\b(.*)", state, re.DOTALL)
    body = spine.group(1)
    assert ".over" in body, (
        "the spine never reads the server's `over` flag; the violation set "
        "would have to be derived here"
    )
    for derived in (r"load\s*>\s*", r"dispatched\s*>\s*", r"\.cap\s*<"):
        assert not re.search(derived, body), (
            f"the spine compares a load against a capacity itself "
            f"(`{derived}`). Both `over` flags are on the wire; a second "
            f"comparison here is one the API can disagree with."
        )


def test_the_degenerate_combination_is_labelled_not_struck(assets):
    """Reachable, and it says why it is flat.

    Striking the combination was rejected because view-aware behaviour is
    exactly the hidden modality the key assignments were designed to avoid.
    Authoring risk into the textbook file was rejected because it invents
    meaningless numbers the room will ask about, in a dataset tuned for a
    completely different property. So the headline states it instead.
    """
    state = COMMENT.sub(" ", assets["state.js"])
    assert DEGENERATE_NOTE in state, (
        f"nothing states {DEGENERATE_NOTE!r}. On the textbook set every cost "
        f"is 1 and there is no risk key, so lambda multiplies zero and all "
        f"eight lambdas return one plan -- a one-beat ladder with the Day 1 "
        f"punchline mute and nothing on screen saying so."
    )
    # And it is a HEADLINE sentence with a slot of its own, not a repurposed
    # A/B label: the pair means "these two numbers differ", and a sentence in
    # that slot would be a claim about a comparison nobody made.
    graph = COMMENT.sub(" ", assets["graph.js"])
    assert "note" in graph, (
        "graph.js builds no headline note slot for the sentence to be written "
        "into"
    )
    # Nothing anywhere strikes a view for a dataset.
    page = COMMENT.sub(" ", assets["index.html"])
    for guard in (r"disabled\s*=", r"cost-risk.{0,200}textbook"):
        assert not re.search(guard, page, re.DOTALL), (
            "index.html makes a view conditional on the dataset. A degenerate "
            "combination is labelled, not struck -- view-aware behaviour is "
            "the hidden modality the key assignments exist to avoid."
        )


def test_day_one_authors_the_violation_hue_the_token_block_was_waiting_for(
        assets, stylesheet):
    """The debt the palette recorded, paid by the ticket that owns the mark.

    `--panel-tick-violating` shipped as a provisional stand-in with a note
    saying the violation has no canvas hue yet and that the ticket authoring it
    should re-derive the tick. This is that ticket.
    """
    defined = _defined_tokens(stylesheet)
    assert "--violation" in defined, (
        "style.css defines no `--violation`. The violation was a provisional "
        "panel tick with no canvas hue behind it; Day 1 is the view that "
        "draws it."
    )
    colours = _colour_tokens(stylesheet)
    assert colours["--violation"] != colours["--node-demand"], (
        "the violation hue is exactly the demand node's. Over-capacity marks "
        "appear beside demand nodes, which is the one place the two must not "
        "be confusable."
    )
    # Both violations reach for the one hue, so "this is the plan failing" is
    # one colour on the board rather than two.
    for selector in (".violation", ".node.overdrawn"):
        rule = re.search(rf"{re.escape(selector)}[^{{]*\{{([^}}]*)\}}", stylesheet)
        assert rule and "--violation" in rule.group(1), (
            f"`{selector}` does not paint with `--violation`"
        )


# ---- dataset and threat-picture cycling (issue #45) -------------------------
# `D` and `T`, the two axes that move WITHOUT leaving the beat the instructor is
# on. What is checked here is what a laptop cannot show: that neither cycle
# resets the story, that the picture's numbers are still the server's, and that
# a key with nothing to do says so rather than looking broken.

# The two cycling mutators. They live in `state.js` for the reason every other
# beat mutator does: the dataset, the threat picture and the beat index are all
# app state, and the keyboard driver in `index.html` may only call them.
CYCLE_MUTATORS = ["cycleThreat", "nextDataset", "stashThreat", "restoreThreat"]

# The labelled no-op, asserted verbatim like the degenerate note above. A key
# that silently does nothing is a key that looks broken, and an implementer who
# reworded this to something vaguer -- or dropped it for a silent `return` --
# would be turning a labelled no-op back into a mute one.
NO_PICTURES_NOTE = "no threat pictures in this dataset"

# The five disruption kinds the server applies. Their names appearing in the
# frontend's code would mean it had started branching on HOW a lane was
# disrupted, which is one step from computing the result itself.
DISRUPTION_KINDS = ["remove_edge", "remove_node", "scale_capacity",
                    "scale_risk", "set_capacity"]


def test_both_cycling_keys_are_bound_and_neither_reaches_a_layer(assets):
    """`D` and `T` join the action table rather than growing a second one.

    The pointer-only rule for layers is only checkable because the keyboard's
    whole action set is one readable block; two tables would be one the test
    reads and one it does not.
    """
    page = COMMENT.sub(" ", assets["index.html"])
    table = re.search(r"const KEY_ACTIONS = \{(.*?)\n    \};", page, re.DOTALL)
    assert table, "index.html no longer has one readable KEY_ACTIONS table"
    for key in ("KeyD", "KeyT"):
        assert key in table.group(1), (
            f"KEY_ACTIONS binds no {key}. The dataset and threat cycles are "
            f"mid-narration controls, so they belong on the keyboard beside the "
            f"beat and view keys rather than in the pointer-only tier."
        )


def test_the_cycles_live_in_state_js(assets):
    """The dataset and the threat picture are app state, like the beat index."""
    code = COMMENT.sub(" ", assets["state.js"])
    for mutator in CYCLE_MUTATORS:
        assert f"export function {mutator}" in code, (
            f"state.js exports no {mutator}. `D` and `T` move app state, and "
            f"every mutation of app state belongs to the module that owns it."
        )


def test_neither_cycle_resets_the_beat_index(assets):
    """Parking on a detent and cycling the threat is the POINT of these keys.

    Both ladders are data-derived, so their length moves under the instructor
    whenever the dataset or the picture does -- which is why carrying the index
    across is a clamp (`setSpine` already does it) rather than an assignment
    either of these functions is allowed to make.
    """
    code = COMMENT.sub(" ", assets["state.js"])
    for mutator in CYCLE_MUTATORS:
        body = re.search(rf"export function {mutator}\b.*?\n\}}", code, re.DOTALL)
        assert body, f"`{mutator}` is not a single readable function"
        assert not re.search(r"\.beat\s*=", body.group(0)), (
            f"`{mutator}` assigns the beat index. The beat is carried across "
            f"both cycles and clamped to the target's ladder, which is what "
            f"`setSpine` does -- an assignment here would restart the story on "
            f"the key whose whole purpose is not to."
        )
    # And the clamp is the one that already exists, rather than a second one.
    install = re.search(r"export function setSpine\b.*?\n\}", code, re.DOTALL)
    assert install and "clampToSpine" in install.group(0), (
        "`setSpine` no longer clamps the beat index, so re-installing a spine "
        "-- which is what both cycles do -- would leave the index pointing past "
        "the end of the new ladder"
    )


def test_the_threat_picture_is_per_dataset_state(assets):
    """The Day 2 excursion comes home to the picture it left.

    Cleared on the way to a dataset with none and restored on the way back, so
    `D` carries what the target can express and drops what it cannot -- and
    remembers the drop rather than making the instructor re-select it.
    """
    code = COMMENT.sub(" ", assets["state.js"])
    assert "threatByDataset" in code, (
        "state.js keeps no per-dataset threat memory, so `D` either loses the "
        "picture permanently or carries a picture name into a dataset that has "
        "never heard of it"
    )
    restore = re.search(r"export function restoreThreat\b.*?\n\}", code, re.DOTALL)
    assert restore, "`restoreThreat` is not a single readable function"
    # The remembered name is CHECKED against the target's own pictures. An
    # unchecked restore would set `state.threat` to a name the new dataset does
    # not declare, and every lookup into `threat_pictures` would come back
    # undefined -- a pristine network the panel claims is under threat.
    assert "threatNames" in restore.group(0), (
        "`restoreThreat` does not check the remembered picture against the "
        "target dataset's own list, so a name from the theater could survive "
        "into the textbook set"
    )


def test_t_is_a_labelled_no_op_where_there_are_no_threat_pictures(assets):
    """A key that silently does nothing is a key that looks broken.

    Two of the three shipped datasets declare no threat picture at all, so this
    is the common case rather than a defensive branch -- and the instructor
    finds out by pressing it, in front of a room.
    """
    code = " ".join(COMMENT.sub(" ", assets[name])
                    for name in ("state.js", "render.js", "index.html"))
    assert NO_PICTURES_NOTE in code, (
        f"nothing states {NO_PICTURES_NOTE!r}. `T` on the textbook set has "
        f"nothing to cycle, and a key that declines in silence is "
        f"indistinguishable from one that is broken."
    )
    state = COMMENT.sub(" ", assets["state.js"])
    cycle = re.search(r"export function cycleThreat\b.*?\n\}", state, re.DOTALL)
    assert cycle, "`cycleThreat` is not a single readable function"
    # The label is state the render pass reads, not a branch in the render pass:
    # whether `T` had anything to do is a fact about the keypress.
    assert "threatNoOp" in cycle.group(0), (
        "`cycleThreat` records nothing when it declines, so the render pass "
        "has no way to say the key was pressed and had nothing to cycle"
    )
    # And it is transient. A label that outlived the keypress would still be on
    # screen three beats later, claiming the current picture is absent.
    resolve = re.search(r"export function resolveBeat\b.*?\n\}", state, re.DOTALL)
    assert resolve and "threatNoOp" in resolve.group(0), (
        "the no-op label is not cleared by `resolveBeat`, so it would outlive "
        "the keypress that produced it and sit under a later beat"
    )


def test_the_threat_cycle_returns_to_baseline(assets):
    """baseline -> each declared picture -> baseline, and it must come home.

    The pristine network is where the comparison is made from, so a cycle that
    only walked the pictures would strand the instructor inside the theater with
    no keystroke back to the untouched case they started from.
    """
    state = COMMENT.sub(" ", assets["state.js"])
    cycle = re.search(r"export function cycleThreat\b.*?\n\}", state, re.DOTALL)
    body = cycle.group(0)
    assert "null" in body, (
        "`cycleThreat` never returns to `null`, which is the pristine network. "
        "The cycle is baseline -> each picture -> baseline; without the last "
        "step there is no key back to the untouched theater."
    )


def test_every_threat_picture_is_prefetched_before_the_first_keypress(assets):
    """`T` is a keypress, and a keypress never awaits a fetch.

    The standing rule of the whole application: ANYTHING A KEYPRESS CAN REACH IS
    FETCHED BEFORE THE FIRST KEYPRESS. A `T` that fetched would be a request
    that can fail while the room watches, and the spine it installs would arrive
    after the key that asked for it.
    """
    page = COMMENT.sub(" ", assets["index.html"])
    assert "threatNames" in page, (
        "index.html never enumerates the dataset's threat pictures, so `T` "
        "would have to fetch on the keypress that reaches it"
    )
    assert page.index("threatNames") < page.index("bindKeys()"), (
        "the threat pictures are enumerated after the keyboard goes live, so "
        "the first `T` could land on payloads that have not arrived"
    )


def test_t_performs_no_structural_dom_change(assets):
    """Only a `D` switch rebuilds the topology pass.

    The DOM is built once per dataset, so a threat picture may only ever change
    classes and text on elements that already exist. A `T` that rebuilt the
    graph would throw away every handle the render pass reaches lanes through --
    and the two would only disagree once some state was set, which is to say in
    front of a room.
    """
    page = COMMENT.sub(" ", assets["index.html"])
    applied = re.search(r"function applyThreat\(\)\s*\{(.*?)\n    \}", page,
                        re.DOTALL)
    assert applied, (
        "index.html has no `applyThreat()`. Switching pictures is installing "
        "the spines built from that picture's payloads -- one function, so the "
        "`T` key and the dataset load cannot do it differently."
    )
    for structural in ("buildGraph", "fetch"):
        assert structural not in applied.group(1), (
            f"`applyThreat` reaches {structural}. A threat picture changes "
            f"classes and text on elements that already exist; the topology "
            f"pass runs once per dataset and never for a picture."
        )
    # `D` is the one that does rebuild, and it goes through the same loader the
    # first paint uses rather than a second path that can drift from it.
    cycle = re.search(r"async function cycleDataset\(\)\s*\{(.*?)\n    \}", page,
                      re.DOTALL)
    assert cycle, "index.html has no `cycleDataset()`"
    assert "load(" in cycle.group(1), (
        "`cycleDataset` does not go through `load`, so a `D` switch would be a "
        "second build path beside the one the first paint uses"
    )
    assert "stashThreat" in cycle.group(1), (
        "`cycleDataset` does not stash the picture before leaving, so the Day 2 "
        "excursion could not come home to the picture it left"
    )


def test_no_disruption_arithmetic_reaches_the_frontend(assets):
    """Every disrupted number comes off the server's `changes` block.

    The alternative is reimplementing five disruption kinds in JavaScript --
    including remove-node's zero-every-incident-edge semantics and a risk clamp
    -- where a divergence puts a capacity on the projector that the API
    disagrees with, mid-class, with nothing raised anywhere.
    """
    for name in ("state.js", "render.js", "graph.js", "index.html"):
        code = COMMENT.sub(" ", assets[name])
        for kind in DISRUPTION_KINDS:
            assert kind not in code, (
                f"{name}: names the disruption kind `{kind}`. The frontend "
                f"never branches on HOW a lane was disrupted -- it reads the "
                f"post-disruption capacity the server already computed."
            )
        # `factor` is the multiplier a scaled lane would be recomputed with.
        assert not re.search(r"\.factor\b", code), (
            f"{name}: reads a disruption's `factor`, which is the multiplier a "
            f"client-side recomputation would need and a reader needs for "
            f"nothing else"
        )
    # And the reading itself is in one place, so there is one lookup rather than
    # one per consumer.
    state = COMMENT.sub(" ", assets["state.js"])
    assert "export function edgeChanges" in state, (
        "state.js exports no `edgeChanges`. The post-disruption state of every "
        "lane is one lookup into what the server computed, so that every lane "
        "in one render pass is judged against the same map."
    )


def test_the_instructor_written_note_is_displayed(assets, stylesheet):
    """The caption that was authored into every scenario file and never drawn.

    `note` is instructor-written narration -- "Forward port struck; its 60 units
    of stock are lost to the plan" -- and on a projector it is the sentence the
    room reads while the numbers move under it. Nothing in the repo has ever
    rendered it.
    """
    page = COMMENT.sub(" ", assets["index.html"])
    assert 'id="threat-note"' in page, (
        "index.html has no threat-note slot. The picture's caption is a fixed "
        "slot like every other, built once and written by textContent."
    )
    graph = COMMENT.sub(" ", assets["graph.js"])
    assert "threat-note" in graph, (
        "graph.js takes no handle on the threat-note slot; the render pass "
        "never appends, so the element has to be reached through the handle map"
    )
    render = COMMENT.sub(" ", assets["render.js"])
    assert "disruptions" in render, (
        "render.js never reads a picture's `disruptions`, which is where the "
        "instructor-written notes are -- the computed `changes` block carries "
        "the numbers and no narration at all"
    )
    assert "#threat-note" in stylesheet, (
        "style.css paints no `#threat-note`; the caption would inherit whatever "
        "the panel's body type happens to be"
    )


def test_a_removed_lane_is_struck_out_rather_than_deleted(assets, stylesheet):
    """The room sees what was taken away, not a gap where it used to be.

    A lane that vanishes teaches less than a lane visibly struck out -- and the
    DOM is built once per dataset, so a threat picture has no way to delete one
    even if it wanted to.
    """
    rule = re.search(r"#ledger tr\.removed td\s*\{([^}]*)\}", stylesheet)
    assert rule, "style.css has no `#ledger tr.removed td` rule"
    assert "line-through" in rule.group(1), (
        "a removed lane's ledger row is not struck through, so a lane the "
        "server has zeroed reads as one that merely lost its emphasis"
    )
    assert "muted" in rule.group(1), (
        "a removed lane's row is not greyed; struck AND greyed is the "
        "vocabulary, and half of it reads as a lane still in play"
    )
    # Nothing anywhere takes an element out of the tree after the build pass.
    for name in ("render.js", "index.html"):
        code = COMMENT.sub(" ", assets[name])
        for removal in (r"\.remove\(\)", r"removeChild"):
            assert not re.search(removal, code), (
                f"{name}: removes an element from the tree. Removal is a style "
                f"and never a deletion -- the lane keeps its element and gains "
                f"a class."
            )


def test_supply_figures_are_qualified_under_a_threat_picture(assets, stylesheet):
    """A severed hub still reports its stock, and the panel must not let that lie.

    Removing a node zeroes its incident lanes and leaves its quantity alone, so
    the network still reports full total supply beside a visibly severed hub --
    which invites exactly the wrong question at the moment the instructor is
    making the opposite point. Resolved in the PANEL rather than by mutating the
    numbers: the total stays the server's.
    """
    state = COMMENT.sub(" ", assets["state.js"])
    assert "export function severedNodes" in state, (
        "state.js exports no `severedNodes`. Which hubs a picture has cut off "
        "is read out of the server's `changes` block -- a node all of whose "
        "lanes are removed -- not worked out from the disruption declarations."
    )
    body = re.search(r"export function severedNodes\b.*?\n\}", state, re.DOTALL)
    assert "isRemoved" in body.group(0), (
        "`severedNodes` does not decide removal through `isRemoved`, so a "
        "severed hub and a struck lane would be answering the same question "
        "two ways"
    )
    # No arithmetic on the quantities. The total is the server's number and
    # stays the server's number; what the panel adds is a count of hubs, which
    # is certified by the struck nodes on the canvas.
    render = COMMENT.sub(" ", assets["render.js"])
    assert "total_supply" in render, "render.js no longer writes the supply slot"
    assert not re.search(r"total_supply\s*[-+]", render), (
        "render.js adjusts `total_supply` itself. The figure is the server's "
        "and stays the server's -- the panel qualifies it rather than mutating "
        "it, or the number on the projector stops matching the API's."
    )
    assert "severed" in render, (
        "nothing marks the severed hubs in the render pass, so the supply "
        "figure would sit unqualified beside a hub with no lanes left"
    )
    assert ".node.severed" in stylesheet, (
        "style.css paints no `.node.severed`; a hub cut off by a threat "
        "picture would look exactly like one still feeding the theater"
    )
