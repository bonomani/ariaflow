# Directives Claude Code - ariaflow (backend)

## General rule — external repos and directories
- On ANY repo or directory other than this one (ariaflow), you MAY ONLY run read-only commands: `cat`, `head`, `grep`, `find`, `ls`, `git log`, `git show`, `git diff` (without write flags).
- NEVER run mutating commands outside this repo: `git add`, `git commit`, `git push`, `git pull`, `git checkout`, `git reset`, `rm`, `mv`, `cp`, `sed`, `pip install`, or any command that modifies files, state, or history.

## Cross-repo boundary — ariaflow-web (frontend)
- The frontend repo is at /home/bc/repos/github/bonomani/ariaflow-web
- The frontend is a separate project. All communication is through the API.
- You MAY NOT read, write, or reference any files in the frontend repo. No exceptions.
- If the user asks you to operate on the frontend repo, remind them of this boundary and suggest they use a separate session from the frontend repo.
- The frontend agent may write to `docs/BACKEND_GAPS.md` to report API gaps. Check this file when starting work — resolve gaps and remove completed items.
