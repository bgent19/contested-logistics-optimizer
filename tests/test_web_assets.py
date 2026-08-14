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
