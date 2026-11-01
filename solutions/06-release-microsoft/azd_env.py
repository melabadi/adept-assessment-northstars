"""Settings for this solution's scripts.

`setting(name)` returns a value from the environment, or from this solution's azd environment (`azd env get-values`,
run in this folder) so presenters do not have to export anything after `azd up`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

SOLUTION = Path(__file__).resolve().parent
REPO = SOLUTION.parents[1] if len(SOLUTION.parents) > 1 else SOLUTION  # in the release jobs' image, the files sit at /release


@lru_cache(maxsize=1)
def azd_values() -> dict[str, str]:
    """Values of this solution's azd environment, or {} when azd is not installed or not initialized here."""
    if not shutil.which("azd"):
        return {}
    proc = subprocess.run(["azd", "env", "get-values", "--output", "json"], capture_output=True, text=True, cwd=SOLUTION)
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def setting(name: str, default: str | None = None) -> str:
    """Environment variable first, then the azd environment, then the default; exits with a clear message if missing."""
    value = os.environ.get(name) or azd_values().get(name) or default
    if not value:
        raise SystemExit(f"error: {name} is not set. Run `azd up` in {SOLUTION.name} first, or export {name}.")
    return value


def utf8_stdout() -> None:
    """Windows consoles default to a legacy code page; force UTF-8 so symbols in reports print correctly."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
