"""Fail closed when a built wheel omits required package files or leaks private assets."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from zipfile import ZipFile


REQUIRED_MEMBERS = {
    "opinion_agent/__init__.py",
    "opinion_agent/api.py",
    "opinion_agent/mcp_server.py",
    "opinion_agent/agent/graph.py",
    "opinion_agent/static/index.html",
    "opinion_agent/static/app.js",
    "opinion_agent/static/styles.css",
    "opinion_agent/static/trace.html",
    "opinion_agent/static/trace-viewer.css",
    "opinion_agent/static/trace-viewer.js",
}
FORBIDDEN_PARTS = {
    ".env",
    "data/raw_private",
    "data/annotations",
    "dictionaries/",
    "artifacts/legacy_baseline",
}


def inspect_wheel(path: str | Path) -> dict[str, object]:
    wheel_path = Path(path)
    if not wheel_path.is_file() or wheel_path.suffix != ".whl":
        return {"passed": False, "missing": sorted(REQUIRED_MEMBERS), "forbidden": []}

    with ZipFile(wheel_path) as archive:
        members = set(archive.namelist())
    missing = sorted(REQUIRED_MEMBERS - members)
    forbidden = sorted(
        member
        for member in members
        if any(part in member for part in FORBIDDEN_PARTS)
    )
    return {"passed": not missing and not forbidden, "missing": missing, "forbidden": forbidden}


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("wheel")
    args = parser.parse_args()
    result = inspect_wheel(args.wheel)
    print(result)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
