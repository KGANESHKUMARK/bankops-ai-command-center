"""Supply-chain hygiene check: flag installed Python packages published < N days ago.

Usage: backend/.venv/Scripts/python scripts/check_dependency_age.py [--days 7]
Queries the public PyPI JSON API for the upload time of each installed version.
Exit code 1 if any package is younger than the threshold.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime
from importlib import metadata


def upload_time(name: str, version: str) -> datetime | None:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 - fixed https host
            data = json.load(resp)
    except Exception:
        return None
    times = [
        datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00"))
        for f in data.get("urls", [])
        if f.get("upload_time_iso_8601")
    ]
    return min(times) if times else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    now = datetime.now(UTC)
    too_new: list[str] = []
    unknown: list[str] = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name, version = dist.metadata["Name"], dist.version
        if name.lower() in {"pip", "setuptools", "wheel"}:
            continue
        ts = upload_time(name, version)
        if ts is None:
            unknown.append(f"{name}=={version}")
            continue
        age = (now - ts).days
        if age < args.days:
            too_new.append(f"{name}=={version} (published {ts.date()}, {age}d ago)")
    for item in unknown:
        print(f"UNKNOWN  {item}")
    for item in too_new:
        print(f"TOO NEW  {item}")
    print(f"Checked installed packages; {len(too_new)} younger than {args.days} days, {len(unknown)} unknown.")
    return 1 if too_new else 0


if __name__ == "__main__":
    sys.exit(main())
