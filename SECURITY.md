# Security policy

GHOSTTRACE never touches real systems: every containment action is a simulation, and approval only records a human
authorisation. Two profiles:

- **Local/demo** (`docker-compose.yml`): shared `X-GT-Demo-Token` header (fails closed if unset), no TLS, all roles.
  Trusted single machine only.
- **Production** (`docker-compose.prod.yml`): OIDC bearer tokens verified against the IdP's JWKS (asymmetric
  algorithms only; `iss`/`aud`/`exp`/`iat`/`sub` required), role- and workspace-based authorisation, HTTPS via Caddy
  with HSTS, password-protected FalkorDB not exposed on the host. `GT_ENV=production` refuses demo auth.

- **Secrets.** Configuration comes only from environment variables (`.env.example` holds placeholders). `.env`
  is git-ignored, and `scripts/secret_scan.sh` runs in CI. Logs redact token- and key-like values. Memory
  quarantines secret-looking content.
- **Data.** Only synthetic data is loaded; the loader rejects scenarios that are not marked `synthetic`.
- **Dependencies.** Exact pins with lockfiles. `make audit` runs `pip-audit` and `npm audit`.
- **Reporting.** This is a hackathon project with no security contact or SLA. Open an issue in the hosting
  repository, and never include real credentials or real company data.

See [docs/threat-model.md](docs/threat-model.md) for the threat model and its residual risks.
