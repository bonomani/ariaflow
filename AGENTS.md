# Agent Instructions — ariaflow-server (backend)

## General rule — external repos and directories
- On ANY repo or directory other than this one (ariaflow-server), you MAY ONLY run read-only commands: `cat`, `head`, `grep`, `find`, `ls`, `git log`, `git show`, `git diff` (without write flags).
- NEVER run mutating commands outside this repo: `git add`, `git commit`, `git push`, `git pull`, `git checkout`, `git reset`, `rm`, `mv`, `cp`, `sed`, `pip install`, or any command that modifies files, state, or history.

## Testing policy
- Every new feature, bug fix, or behavior change MUST include tests in the same commit.
- Do not ship code without tests — no exceptions.
- Tests must cover the new code paths, not just pass existing ones.
- Register new tests in `docs/governance/tic-oracle.md` with Intent / Oracle / Trace Target.

## BGS governance updates
When your change affects governed artifacts, update them in the same commit:
- **New tests** → register in `docs/governance/tic-oracle.md`, update test count in BGS.md + bgs-decision.yaml
- **New boundary/interaction** → add to `docs/governance/biss-classification.md`, update boundary count in BGS.md + bgs-decision.yaml
- **State model change** → update `docs/governance/asm-state-model.md`
- **New preference/gate** → update `src/ariaflow_server/contracts.py` (source of truth for UIC)

## Cross-repo boundary — ariaflow-web (frontend)
- The frontend repo is at /home/bc/repos/github/bonomani/ariaflow-web
- The frontend is a separate project. All communication is through the API.
- You MAY NOT read, write, or reference any files in the frontend repo. No exceptions.
- If the user asks you to operate on the frontend repo, remind them of this boundary and suggest they use a separate session from the frontend repo.
- The frontend agent may write to `docs/BACKEND_GAPS_REQUESTED_BY_FRONTEND.md` to report API gaps. Check this file when starting work — resolve gaps and move them to the Resolved section. Do not add or delete entries yourself (that's the frontend's responsibility).
