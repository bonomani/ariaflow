# GAP: Rename GitHub repo bonomani/ariaflow → bonomani/ariaflow-server

## GitHub
- [ ] `gh repo rename ariaflow-server -R bonomani/ariaflow`
- [x] Verify remote already set: `git remote get-url origin` → `https://github.com/bonomani/ariaflow-server.git`

## Code rename — DONE (2026-04-09)
- [x] All API keys `"ariaflow"` → `"ariaflow-server"` in source, tests, openapi specs
- [x] Bonjour service type `_ariaflow._tcp` → `_ariaflow-server._tcp`
- [x] Docs updated (CLAUDE.md, SECURITY.md, ARCHITECTURE.md, SPEC.md, governance/)
- [x] Git remote URL updated locally
- [x] All 515 tests pass
