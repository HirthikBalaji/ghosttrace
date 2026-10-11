"""CLI: python -m verifier check cert.json edges.jsonl"""

from __future__ import annotations

import json
import sys

from verifier.core import check


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] != "check":
        print("usage: python -m verifier check CERT.json EDGES.jsonl", file=sys.stderr)
        return 2
    try:
        with open(argv[2], encoding="utf-8") as fh:
            cert = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"REJECTED: cannot read certificate: {exc}")
        return 1
    errors = check(cert, argv[3])
    if errors:
        print("REJECTED")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"ACCEPTED {cert.get('certificate_id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
