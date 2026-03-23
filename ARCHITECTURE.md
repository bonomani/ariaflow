# Ariaflow Engine Architecture

## 1. Short Overview

Ariaflow is a headless download engine.
It manages queue state, sessions, runs, and policy.
The engine exposes its state through an HTTP API.
The web UI is a separate client and is documented elsewhere.

## 2. Canonical Model

The architecture is intentionally orthogonal:

- one concept, one job
- one layer, one question
- one policy, one responsibility

## 3. Core Concepts

### Status / Readiness

Question: can the system run safely?

- service status
- preflight checks
- dependency checks

### Policy

Question: how should the engine behave?

Policy defines defaults. It does not own runtime state.

- run policy
- queue policy
- group policy
- job policy

### Session

Question: when and under which context did the engine operate?

A session is the lifecycle container for one engine use period.

- `started_at`
- `last_seen_at`
- `closed_at`

### Run

Question: what is the engine doing right now?

A run is one execution cycle inside a session.

- `state`: running / paused / stopped
- `started_at`
- `ended_at`

### Queue

Question: what work exists and in what order?

The queue is the ordered list of work being processed.

### Group

Question: which jobs belong together?

A group is a named set of jobs inside one queue.

### Job

Question: what is the state of this one item?

A job is one unit of work, usually one URL or one download item.

## 4. Relationships

```text
Status / Readiness -> tells if the system can start
Policy -> controls how Run / Queue / Group / Job behave
Session -> contains Run
Run -> processes Queue
Queue -> contains Group
Group -> contains Job
```

## 5. Policy Placement

Policy should apply where it changes behavior, not where it merely labels data.

```text
Policy
├── Run policy
│   ├── mode: normal / debug
│   └── preflight: on / off
├── Queue policy
│   ├── concurrency
│   ├── dedupe
│   └── ordering rules
├── Group policy
│   ├── group_priority
│   └── recovery handling
└── Job policy
    ├── job_priority
    └── post_action_rule
```

Rules:

- `preflight` belongs with readiness and run start checks.
- `concurrency` belongs with queue scheduling.
- `dedupe` belongs with queue selection.
- `group_priority` belongs with group ordering.
- `job_priority` belongs with job ordering.
- `post_action_rule` is a job behavior with a global default.

## 6. Full Structural View

```text
Status / Readiness
├── service status
├── preflight
└── dependency checks

Policy
├── Run policy
│   ├── mode: normal / debug
│   └── preflight: on / off
├── Queue policy
│   ├── concurrency
│   ├── dedupe
│   └── ordering rules
├── Group policy
│   ├── group_priority
│   └── recovery handling
└── Job policy
    ├── job_priority
    └── post_action_rule

Session
├── started_at
├── last_seen_at
├── closed_at
└── Run
    ├── state: running / paused / stopped
    ├── started_at
    ├── ended_at
    └── Queue
        ├── Group A
        │   ├── group_priority: 10
        │   └── Jobs
        │       ├── Job A1
        │       │   ├── job_priority: default
        │       │   ├── status
        │       │   └── post_action_rule: inherited/default
        │       └── Job A2
        │           ├── job_priority: 5
        │           └── post_action_rule: custom
        │
        └── Group B
            ├── group_priority: 3
            └── Jobs
                └── Job B1

Observability
├── progress
├── recent actions
├── errors
└── raw logs / debug
```

## 7. Design Rules

- Keep one term = one meaning.
- Keep one layer = one question.
- Keep debug close to the object it explains.
- Keep noisy traces in the evidence layer.
- Keep the main work surface simple.
- Do not duplicate the same truth in multiple places.
- Use policy for defaults, not for runtime identity.
- Prefer orthogonal boundaries over clever abstractions.

## 8. AI / Human Documentation Rules

- Start with a short summary.
- Put exact definitions in the middle.
- Put diagrams near the end.
- Keep the language plain.
- Keep the relationships explicit.
- Keep one canonical document for the engine.
- Keep UI behavior and engine behavior documented in separate files.

## 9. UI Mapping

- `Status / Readiness` maps to engine health and preflight.
- `Policy` maps to engine settings and defaults.
- `Session / Run` maps to the current execution context.
- `Queue` maps to active work.
- `Observability` maps to logs and evidence.

## 10. Orthogonal Questions

- `Status / Readiness`: can it run?
- `Policy`: how should it run?
- `Session / Run`: what is running now?
- `Queue`: what work exists?
- `Observability`: what happened and why?
