# Security update cadence

Recommended schedule for security maintenance.

---

## Monthly audit + patch window

- Run `pip-audit -r requirements.txt` (or equivalent) to check for known vulnerabilities
- Review CVEs and update pinned dependencies in `requirements.txt`
- Run full test suite and smoke script
- Deploy updates to staging first, then prod

---

## Critical CVE fast-track

For **critical** vulnerabilities (e.g. RCE, auth bypass):

1. Patch within **48 hours** when feasible
2. Update `requirements.txt` with patched version
3. Run tests; deploy to prod
4. Document the CVE and fix in commit message or release notes

---

## See also

- [TOKEN_ROTATION_AND_INCIDENT_RESPONSE.md](TOKEN_ROTATION_AND_INCIDENT_RESPONSE.md)
- [BROKER_BACKUP_RETENTION.md](BROKER_BACKUP_RETENTION.md)
