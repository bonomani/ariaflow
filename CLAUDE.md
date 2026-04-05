# Directives Claude Code - ariaflow (backend)

## Cross-repo boundary
- NEVER read, write, edit, commit, push, or perform any operation on files in the frontend repo (ariaflow-web). This includes git operations.
- If the user asks you to operate on the frontend repo, remind them of this boundary and suggest they use a separate session from the frontend repo.
- The frontend is a separate project. All communication is through the API.
- The frontend agent may write to `docs/BACKEND_GAPS.md` to report API gaps. Check this file when starting work — resolve gaps and remove completed items.
