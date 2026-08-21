# Domain docs

This is a single-context repository.

## Before exploring

Read `CONTEXT.md` at the repository root when it exists. Read relevant decisions in `docs/adr/` before working in an area covered by them.

If these files do not exist, proceed without treating their absence as a problem. Create them lazily when the domain language or a durable decision needs to be recorded.

## Layout

```text
/
├── CONTEXT.md
├── docs/adr/
└── docs/agents/
```

## Vocabulary

Use the terms defined in `CONTEXT.md` in issue titles, specifications, test names, and implementation plans. If a concept is missing or ambiguous, resolve it through domain modeling before introducing a new term.

## ADRs

If a proposed decision conflicts with an existing ADR, call out the conflict explicitly and explain why reopening the decision is warranted.
