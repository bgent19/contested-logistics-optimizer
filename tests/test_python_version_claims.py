"""The Python version we advertise must be a version we actually run.

`pyproject.toml` once said `requires-python = ">=3.10"` while CI ran only
3.12 and the `Dockerfile` built on `python:3.12-slim`. Nothing verified the
floor, so a 3.11-only construct could merge green and then fail on the very
interpreter the package told students it supported. In a teaching repo that
failure lands on day one, on a student laptop, during setup.

The repo now claims what it tests: 3.12, in all three places. This file is
the thing that keeps the three agreeing. Widen `requires-python` and this
test fails until CI is widened to match -- which is the whole point, and is
why the fix is "add the version to CI", never "loosen this test".

Parsing the workflow with a regex rather than a YAML library is deliberate:
`pyyaml` is not a dependency of this project and adding one so a test can
read a config file would be a poor trade. The regex handles the single-pin
form and the matrix form alike, because it takes every version literal
attached to a `python-version` key.

Two things the parser has to get right, both learned the hard way in review:

- **Comments are not configuration.** A commented-out `# - "3.10"` must not
  count as a version CI runs, or this file passes on evidence that does not
  exist -- the exact failure it was written to prevent. Comments are stripped
  before anything is matched.
- **Ambiguity fails closed.** Where the parser cannot be sure, the test
  errors rather than shrugs. A quiet pass here is worth nothing.
"""

import os
import re
import tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "test.yml")
DOCKERFILE = os.path.join(ROOT, "Dockerfile")

# Any `X.Y` on a `python-version` line is a Python version -- quoted with
# either style, or bare. Bare is accepted so the parser sees a version that
# YAML itself would mangle (unquoted `3.10` is the float 3.1), which
# `test_workflow_quotes_its_python_versions` then reports properly.
VERSION = re.compile(r"\d+\.\d+")


def _as_tuple(version):
    """`"3.10"` -> `(3, 10)`, so 3.9 < 3.10 rather than the string order."""
    return tuple(int(part) for part in version.split("."))


def declared_floor():
    """The lowest interpreter `pyproject.toml` promises to support."""
    with open(PYPROJECT, "rb") as handle:
        requires = tomllib.load(handle)["project"]["requires-python"]

    match = re.fullmatch(r">=\s*(\d+\.\d+)", requires.strip())
    assert match, (
        f"requires-python is {requires!r}; this test only understands a "
        f'simple ">=X.Y" floor. Teach it the new form rather than deleting it.'
    )
    return match.group(1)


def _uncommented(line):
    """The configuration part of a line, with any `#` comment removed.

    A commented-out version is not a version CI runs. Counting one would
    make this whole file pass on evidence that does not exist.
    """
    return line.split("#", 1)[0]


def _indent(line):
    return len(line) - len(line.lstrip())


def _workflow_version_lines():
    """Every line of the workflow that declares a Python version.

    Yields the `python-version:` key lines themselves, plus the list items
    belonging to one -- a matrix block's entries are indented under the key,
    so the walk stops as soon as indentation returns to the key's level or
    shallower. Without that check it would read on into the next step, whose
    items also start with `-`.

    Comments are stripped before any of this, so a commented-out entry is
    invisible here.
    """
    with open(WORKFLOW, encoding="utf-8") as handle:
        lines = [_uncommented(raw) for raw in handle.read().splitlines()]

    for index, line in enumerate(lines):
        if "python-version" not in line:
            continue

        yield line
        for following in lines[index + 1 :]:
            if not following.strip():
                continue
            if _indent(following) <= _indent(line):
                break
            if not following.strip().startswith("-"):
                break
            yield following


def ci_versions():
    """Every Python version the `tests` workflow actually runs.

    A `python-version:` whose value is a `${{ matrix.* }}` reference
    contributes nothing itself; the versions come from the matrix
    declaration it points at, which this also reads.
    """
    found = []
    for line in _workflow_version_lines():
        found.extend(VERSION.findall(line))

    return sorted(set(found), key=_as_tuple)


def docker_version():
    """The Python the container image is built on."""
    with open(DOCKERFILE, encoding="utf-8") as handle:
        match = re.search(r"^FROM python:(\d+\.\d+)", handle.read(), re.M)

    assert match, "Dockerfile has no `FROM python:X.Y` line to check"
    return match.group(1)


def test_ci_runs_at_least_one_python_version():
    # Guards the guard: an empty parse would make every test below vacuous.
    assert ci_versions(), f"no python-version literals found in {WORKFLOW}"


def test_ci_runs_the_version_pyproject_advertises_as_its_floor():
    floor = declared_floor()
    versions = ci_versions()

    assert floor in versions, (
        f"pyproject.toml advertises support back to Python {floor}, but CI "
        f"runs only {versions}. Nothing verifies the claim. Either add "
        f"{floor} to the workflow, or raise requires-python to "
        f"{versions[0]} -- see the note above requires-python."
    )


def test_ci_runs_nothing_below_the_advertised_floor():
    floor = declared_floor()
    below = [v for v in ci_versions() if _as_tuple(v) < _as_tuple(floor)]

    assert not below, (
        f"CI runs {below}, which requires-python (>={floor}) says is "
        f"unsupported. A green run there proves nothing about a version "
        f"users are told not to install on."
    )


def test_workflow_quotes_its_python_versions():
    """Unquoted `3.10` is the float 3.1 to YAML, and setup-python obeys it.

    The failure that causes is remote from its cause -- a job that installs
    3.1, or errors on a version that does not exist -- so catch it here,
    where the message can say what actually went wrong.
    """
    unquoted = [
        line.strip()
        for line in _workflow_version_lines()
        if VERSION.search(line) and not re.search(r"""['"]\d+\.\d+['"]""", line)
    ]

    assert not unquoted, (
        f"unquoted Python versions in {WORKFLOW}: {unquoted}. YAML reads a "
        f"bare 3.10 as the number 3.1. Quote them."
    )


def test_classifiers_match_the_versions_ci_runs():
    """The classifier list is a version claim too -- PyPI shows it to users.

    It is the newest of the declaration sites and the easiest to forget,
    which is exactly why it is asserted rather than trusted.
    """
    with open(PYPROJECT, "rb") as handle:
        classifiers = tomllib.load(handle)["project"].get("classifiers", [])

    claimed = sorted(
        (
            match.group(1)
            for match in (
                re.fullmatch(r"Programming Language :: Python :: (\d+\.\d+)", c)
                for c in classifiers
            )
            if match
        ),
        key=_as_tuple,
    )

    assert claimed == ci_versions(), (
        f"classifiers advertise Python {claimed} but CI runs {ci_versions()}. "
        f"The two lists have to be the same list."
    )


def test_the_readme_tells_students_the_right_floor():
    """The README is where a student learns which Python to install.

    A stale number here sends someone to the wrong installer before they
    ever reach a traceback.
    """
    floor = declared_floor()
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
        readme = handle.read()

    assert f"Python {floor}" in readme, (
        f"README.md never names Python {floor}, the floor requires-python "
        f"advertises. Students read the README, not pyproject.toml."
    )


def test_the_container_runs_a_tested_version():
    version = docker_version()

    assert version in ci_versions(), (
        f"Dockerfile builds on Python {version}, which CI never runs. The "
        f"image is the runtime students get from `docker compose up`; it "
        f"should not be the one interpreter nothing tests."
    )
