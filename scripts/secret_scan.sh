#!/usr/bin/env bash
# Minimal secret scan over tracked files (CI also runs gitleaks when available).
set -euo pipefail
cd "$(dirname "$0")/.."
pat='(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{32,})'
# the memory-service test intentionally contains a fake AWS-style key to prove quarantine; it is allowlisted
hits=$(git ls-files | grep -v -E '(^backend/tests/test_integration_agents.py$|^scripts/secret_scan.sh$|^backend/app/memory/service.py$)' \
  | xargs grep -nE "$pat" 2>/dev/null || true)
if [[ -n "$hits" ]]; then echo "possible secrets:"; echo "$hits"; exit 1; fi
if git ls-files | grep -qx ".env"; then echo ".env is tracked"; exit 1; fi
echo "secret scan: clean ($(git ls-files | wc -l | tr -d ' ') tracked files)"
