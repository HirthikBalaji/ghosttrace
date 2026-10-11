"""Run the independent verifier (`verifier/`, stdlib-only, shares no code with the planner) in a separate process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from app.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def run_verifier(cert: dict[str, Any], lines: list[dict[str, Any]], tag: str) -> dict[str, Any]:
    d = (REPO_ROOT / get_settings().artifact_dir.replace("../", "")).resolve() / "verify"
    d.mkdir(parents=True, exist_ok=True)
    stem = f"{tag}-{uuid.uuid4().hex[:8]}"
    cpath, epath = d / f"{stem}.cert.json", d / f"{stem}.edges.jsonl"
    cpath.write_text(json.dumps(cert))
    epath.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell; paths are server-generated
            [sys.executable, "-E", "-s", "-m", "verifier", "check", str(cpath), str(epath)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    finally:
        for f in (cpath, epath):
            f.unlink(missing_ok=True)
    return {
        "exit_code": proc.returncode,
        "accepted": proc.returncode == 0,
        "output": proc.stdout.strip()[:4000],
        "stderr": proc.stderr.strip()[-1000:],
        "command": "python -m verifier check cert.json edges.jsonl",
    }
