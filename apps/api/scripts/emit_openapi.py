#!/usr/bin/env python
"""Emit ``packages/openapi/openapi.yaml`` from the FastAPI app.

Phase 2e: this script is the single source of truth for the client SDK
schema.  Run via ``make openapi`` whenever a route or model changes;
``make openapi-check`` (which calls this script with ``--check``) diffs
and CI fails on drift.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

# Skip the SSM cold-start fetch — emit doesn't need real config.
os.environ.setdefault("CONTRICOOL_SKIP_COLD_START_CONFIG", "1")

import yaml  # noqa: E402

from app.main import app  # noqa: E402

OUTPUT = Path(__file__).resolve().parents[3] / "packages" / "openapi" / "openapi.yaml"


_API_VERSION_PREFIX = "/v1"


def _build_spec() -> dict[str, Any]:
    spec: dict[str, Any] = app.openapi()
    # Strip server-list (origin-neutral spec) and add a description so
    # the YAML is self-describing for SDK consumers.
    spec.pop("servers", None)
    info = spec.setdefault("info", {})
    info["description"] = (
        "ContriCool API — Phase 2c email-only auth backend "
        "(/v1/auth/*). Generated from FastAPI; do not hand-edit."
    )
    # Strip the /v1 version prefix from path keys.  The SDK consumer
    # supplies it via baseUrl (e.g. EXPO_PUBLIC_API_BASE_URL=/v1) so
    # path keys stay short and stable across version bumps.
    paths = spec.get("paths", {})
    rewritten = {}
    for path, value in paths.items():
        if path.startswith(_API_VERSION_PREFIX):
            rewritten[path[len(_API_VERSION_PREFIX) :] or "/"] = value
        else:
            rewritten[path] = value
    spec["paths"] = rewritten
    return spec


def render() -> str:
    spec = _build_spec()
    return yaml.safe_dump(spec, sort_keys=True, indent=2, allow_unicode=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Diff against the committed YAML; exit 1 on drift.",
    )
    args = parser.parse_args(argv)

    rendered = render()

    if args.check:
        existing = OUTPUT.read_text() if OUTPUT.exists() else ""
        if existing != rendered:
            sys.stderr.write(
                "openapi.yaml drift detected.\n"
                "Run `make openapi` and commit the result.\n"
            )
            # Print a tiny hint of the diff so reviewers can spot the
            # source quickly.
            import difflib

            diff = list(
                difflib.unified_diff(
                    existing.splitlines(keepends=True),
                    rendered.splitlines(keepends=True),
                    fromfile="committed",
                    tofile="generated",
                    n=2,
                )
            )
            sys.stderr.writelines(diff[:60])
            return 1
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered)
    sys.stderr.write(f"wrote {OUTPUT}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
