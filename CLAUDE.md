# Directives Claude Code - ariaflow (backend)

## Cross-repo boundary
- NEVER read, write, or reference files in the frontend repo (ariaflow-web).
- The frontend is a separate project. All communication is through the API.
- The frontend agent may write to `docs/BACKEND_GAPS.md` to report API gaps. Check this file when starting work — resolve gaps and remove completed items.
