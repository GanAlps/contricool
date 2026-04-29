"""Guard test — Dockerfile pip-install pins must match pyproject deps.

Phase 2c added ``boto3`` (and four other packages) to ``pyproject.toml``
but the ``Dockerfile`` carried a hand-written pip-install list that was
not updated. CI tests passed because they ran in the master venv; the
container image quietly shipped without ``boto3``, and every Lambda
invocation crashed at cold start with ``ModuleNotFoundError`` once the
``live`` alias started pointing at the Phase 2c image.

This test diffs the two sources of truth. If you add a runtime
dependency, you must add it to *both* files, and this test must keep
passing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]


_API_DIR = Path(__file__).resolve().parents[1]
_DOCKERFILE = _API_DIR / "Dockerfile"
_PYPROJECT = _API_DIR / "pyproject.toml"

# Comments live in pyproject.toml only — the runtime image has no notion of
# dev-time tooling. ``dev`` extras (pytest, ruff, …) are intentionally not
# installed in the image.


def _normalize(spec: str) -> str:
    """Strip whitespace, quotes, and the version operator block.

    ``"pydantic[email]==2.9.2"`` and ``pydantic[email]>=2.9.2`` both reduce
    to ``pydantic[email]`` so we compare *what is installed*, not the
    pinning strategy. The version match is checked separately below.
    """
    spec = spec.strip().strip('"').strip("'")
    return re.split(r"[<>=!~]", spec, maxsplit=1)[0].strip()


def _pyproject_runtime_deps() -> list[str]:
    data = tomllib.loads(_PYPROJECT.read_text())
    return list(data["project"]["dependencies"])


def _dockerfile_pip_deps() -> list[str]:
    """Parse the ``RUN pip install`` line in the Dockerfile.

    The line spans multiple physical lines via ``\\`` continuation. We
    take the first ``pip install`` block and harvest every quoted token.
    """
    text = _DOCKERFILE.read_text()
    match = re.search(
        r"RUN pip install --no-cache-dir((?:\s*\\\s*\".+?\")+)", text
    )
    if match is None:
        raise AssertionError("Could not locate `RUN pip install` block in Dockerfile")
    return re.findall(r'"([^"]+)"', match.group(1))


def test_dockerfile_installs_every_runtime_dep() -> None:
    """Every runtime dep in pyproject.toml must appear in the Dockerfile.

    A missing entry means the image will throw ``ModuleNotFoundError``
    at cold start the moment that module is imported.
    """
    pyproject = {_normalize(d) for d in _pyproject_runtime_deps()}
    dockerfile = {_normalize(d) for d in _dockerfile_pip_deps()}
    missing = pyproject - dockerfile
    assert not missing, (
        f"Dockerfile is missing runtime deps that pyproject.toml lists: "
        f"{sorted(missing)}. Add them to apps/api/Dockerfile."
    )


def test_dockerfile_does_not_install_unknown_deps() -> None:
    """The reverse — anything pinned in the Dockerfile but absent from
    pyproject.toml is dead weight at best and a security/audit blind
    spot at worst (it ships in the image but no source-of-truth records
    why)."""
    pyproject = {_normalize(d) for d in _pyproject_runtime_deps()}
    dockerfile = {_normalize(d) for d in _dockerfile_pip_deps()}
    extra = dockerfile - pyproject
    assert not extra, (
        f"Dockerfile installs deps that pyproject.toml does not list: "
        f"{sorted(extra)}. Add them to apps/api/pyproject.toml or remove "
        f"them from the Dockerfile."
    )


@pytest.mark.parametrize(
    ("name",),
    [(d,) for d in (_pyproject_runtime_deps() if _PYPROJECT.exists() else [])],
)
def test_dockerfile_version_pin_matches_pyproject(name: str) -> None:
    """For each runtime dep, the Dockerfile must use the exact same
    version specifier as pyproject.toml. Otherwise the venv used by
    tests and the image used in production drift on a minor release —
    which is exactly the class of bug we are trying to prevent."""
    dockerfile_specs = {
        _normalize(d): d.strip().strip('"').strip("'")
        for d in _dockerfile_pip_deps()
    }
    key = _normalize(name)
    docker_spec = dockerfile_specs.get(key)
    expected = name.strip()
    assert docker_spec == expected, (
        f"Version specifier drift for {key!r}: pyproject.toml says "
        f"{expected!r}, Dockerfile says {docker_spec!r}."
    )
