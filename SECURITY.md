# Security policy

GHOSTTRACE is a **synthetic demo**. It ships with demo-only authentication (a shared header token that fails
closed if unset). It has no TLS and no per-user authorisation. Run it only on a trusted local machine. Every
containment action is a simulation; the software never touches real systems.

- **Secrets.** Configuration comes only from environment variables (`.env.example` holds placeholders). `.env`
  is git-ignored, and `scripts/secret_scan.sh` runs in CI. Logs redact token- and key-like values. Memory
  quarantines secret-looking content.
- **Data.** Only synthetic data is loaded; the loader rejects scenarios that are not marked `synthetic`.
- **Dependencies.** Exact pins with lockfiles. `make audit` runs `pip-audit` and `npm audit`.
- **Reporting.** This is a hackathon project with no security contact or SLA. Open an issue in the hosting
  repository, and never include real credentials or real company data.

See [docs/threat-model.md](docs/threat-model.md) for the threat model and its residual risks.
