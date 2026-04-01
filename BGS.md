# BGS Entry

project_name: ariaflow
bgs_slice: BGS-State-Modeled-Governed-Verified
decision_reason: "Stateful download engine with session/run lifecycle, preflight gates, and explicit execution contracts — requires ASM-based state model with preflight governance"
applies_to_scope: "engine execution path: session → run → queue → job lifecycle"
decision_record_path: "./docs/governance/bgs-decision.yaml"
last_reviewed: 2026-04-01
read_next:
  - "./ARCHITECTURE.md"
  - "./docs/governance/asm-state-model.md"
  - "./docs/governance/tic-oracle.md"
  - "./src/aria_queue/contracts.py"
  - "./tests/"
