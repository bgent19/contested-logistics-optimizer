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
form and the matrix form alike, because it takes every quoted version
literal attached to a `python-version` key.
"""

import os
import re
import tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "test.yml")
DOCKERFILE = os.path.join(ROOT, "Dockerfile")

VERSION = re.compile(r'"(\d+\.\d+)"')


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


def ci_versions():
    """Every Python version the `tests` workflow actually runs.

    Collects the quoted literals on each `python-version:` key, plus those
    on the indented list items that follow one. A `python-version:` whose
    value is a `${{ matrix.* }}` reference contributes nothing itself; the
    versions come from the matrix declaration it points at.
    """
    with open(WORKFLOW, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    found = []
    for index, line in enumerate(lines):
        if "python-version" not in line:
            continue

        found.extend(VERSION.findall(line))
        for following in lines[index + 1 :]:
            if not following.strip().startswith("-"):
                break
            found.extend(VERSION.findall(following))

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


def test_the_container_runs_a_tested_version():
    version = docker_version()

    assert version in ci_versions(), (
        f"Dockerfile builds on Python {version}, which CI never runs. The "
        f"image is the runtime students get from `docker compose up`; it "
        f"should not be the one interpreter nothing tests."
    )
