# Context Engine

Last updated: lab@a5fe38d8 | 2026-09-13

## Scope

This spec covers the typed observability layer in `src/context_engine/`, the
owner-scoped `context_breakdown` route in
`routes/history/history_routes.py`, and the frontend Inspector in
`static/js/contextInspector.js`.

## 0.3.0 Contract

Context Engine 0.3.0 observes persisted session context without changing prompt
assembly, compaction, trimming, provider payloads, or tool execution.

`ContextItem` records:

- stable item and category identifiers;
- heuristic token estimate;
- trust classification;
- owner/project/session provenance;
- whether the item is protected;
- only supported controls.

`ContextManifest` exposes two explicitly different lenses:

- `session`: estimated persisted history usage;
- `last_turn`: latest provider/request metrics when available.

The manifest never returns raw prompt, memory, RAG, tool-result, or message
content. Labels are bounded descriptors and provenance contains identifiers,
not credentials or query-bearing URLs.

## Categories

Every response includes these categories in stable order:

1. system;
2. conversation;
3. memory;
4. project;
5. files / RAG;
6. knowledge;
7. tools;
8. MCP.

Empty categories remain present so UI and automation can depend on a stable
shape.

## Model Profile And Budget

The profile reports discovered context length, whether it is known, confidence,
and an XS/S/M/L/unknown tier. Unknown windows keep the conservative 6000-token
agent budget rather than scaling from the unproven 128k fallback.

Budget output distinguishes the configured value, explicit versus automatic
mode, hard maximum, and current effective soft budget. Counts remain marked
`heuristic` unless provider usage explicitly reports real values.

## 0.3.1 Unified Route Budget

`src/context_engine/budget.py` is the single route allocator used by normal
chat, foreground chat fallbacks, and agent routes. It resolves each concrete
model window, preserves the conservative unknown-window budget, reserves output
tokens, estimates native/MCP tool schema overhead, calls the established
`trim_for_context` implementation, and returns one `RouteBudgetPlan`.

Fallback candidates are still shaped independently from the same route-neutral
messages. Compaction remains non-persistent until a winning route is known.
Agent rounds invoke the allocator again as tool results grow, and metrics persist
the answering route's allocation plan for the next Context Inspector request.

## API

```text
GET /api/session/{session_id}/context_breakdown
```

The route uses the same chat API-token scope and owner check as session history.
Foreign sessions return 404. Project settings are loaded only after the session
owner is verified.

## Inspector

Clicking the existing context pill opens an accessible dialog on desktop and a
bottom sheet on mobile. It supports:

- Session and Last turn lenses;
- category totals and provenance drill-down;
- explicit Trusted/Untrusted text;
- existing Compact action;
- links to Memory and Agent settings.

Generic block removal, trust override, pin, priority, and compaction locks are
not exposed because no stable mutable block API exists yet.

## Current Gaps

- 0.3.0 reconstructs evidence from persisted history and latest assistant
  metadata; it does not capture the exact provider payload.
- Tool and MCP schemas are estimated rather than provider-tokenized; schema
  selection reduction is a later policy step when schemas alone exceed budget.
- Chat and agent share one allocator, while compaction orchestration remains in
  their existing route owners.
- Project RAG and skills isolation is not implemented.
- Context items are read-only until later 0.3 slices introduce stable block
  identities and mutation policy.
