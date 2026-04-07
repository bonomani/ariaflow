# BGS Entry

project_name: ariaflow
bgs_slice: BGS-State-Modeled-Governed-Verified
decision_reason: >
  Stateful download engine with session/run lifecycle, preflight gates,
  and explicit execution contracts. The scope depends on installation,
  runtime readiness, recovery, and transition legality — requires
  ASM-based state model with preflight governance.
applies_to_scope: "engine execution path: session → run → queue → job lifecycle, distribution pipeline, service discovery, installation lifecycle"
decision_record_path: "./bgs-decision.yaml"
last_reviewed: 2026-04-05

members_used:
  - BISS — boundary classification (17 boundaries, 10 interaction classes)
  - ASM — state model (4 axes: session, run, job, daemon; 6 coherence rules)
  - UIC — preflight gates (aria2_available, queue_readable) + 27 preferences
  - UCC — structured execution results (UCCResult dataclass)
  - TIC — test oracle (473 tests, trace targets across ASM/UIC/UCC/BISS)

overlays_used: []

external_controls:
  IAM_and_authorization: not_applicable
  sandboxing_or_runtime_isolation: delegated
  secret_and_token_lifecycle: not_applicable
  rate_limiting_and_budget_control: implemented
  privacy_and_data_boundary_control: not_applicable

bgs_version_ref: bgs@58c1467
member_version_refs:
  ucc: ucc@58c1467
  uic: uic@58c1467
  asm: asm@58c1467
  tic: tic@58c1467

read_next:
  - "./docs/ARCHITECTURE.md"
  - "./docs/STATES_AND_INTERACTIONS.md"
  - "./docs/governance/asm-state-model.md"
  - "./docs/governance/biss-classification.md"
  - "./docs/governance/tic-oracle.md"
  - "./docs/governance/bgs-decision.yaml"
  - "./docs/ARIA2_RPC_WRAPPERS.md"
  - "./src/aria_queue/contracts.py"
  - "./tests/"
