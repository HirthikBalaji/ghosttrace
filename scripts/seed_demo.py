"""Seed (or reset) a workspace from a synthetic scenario. Usage: python scripts/seed_demo.py <scenario> [workspace]"""

import json
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "backend"), str(Path(__file__).resolve().parents[1])]

from app.graph.client import GraphClient  # noqa: E402
from app.ingestion.seed import seed  # noqa: E402

scenario = sys.argv[1] if len(sys.argv) > 1 else "ghost_credential_a"
ws = sys.argv[2] if len(sys.argv) > 2 else "demo"
c = GraphClient()
if not c.ping():
    sys.exit("FalkorDB is not reachable (GT_FALKORDB_HOST/GT_FALKORDB_PORT)")
stats = seed(c, ws, scenario)
print(json.dumps({k: v for k, v in stats.items() if k != "nominations"}))
print("latent nominations:", [(n["template_id"], n["src"], n["dst"], n["accepted"]) for n in stats["nominations"]])
