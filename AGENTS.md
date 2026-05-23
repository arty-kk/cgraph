# AGENTS.md

Repository-level operating contract for Codex Cloud and other coding agents.

## Instruction priority

Use this order when guidance conflicts:

1. Current task, issue, PR description, and acceptance criteria.
2. Active `AGENTS.md` chain, including closer directory-level instructions.
3. Repository evidence: source, tests, configs, schemas, migrations, lockfiles, scripts, routes, assets, runtime files, CI, and deployment files.
4. `README.md`, `DESIGN.md`, architecture docs, ADRs, generated maps, and domain docs.
5. Official docs or primary standards for third-party APIs, SDKs, tools, platforms, browser behavior, payments, legal/security requirements, or current facts.

If a local instruction is more specific, follow it. If it weakens safety, security, verification, or task scope, surface the conflict and choose the safer rule.

## Codex Cloud operating rules

- Treat the cloud worktree as the only editable state. Do not rely on unstated local files, secrets, network access, services, or deployment targets.
- Keep diffs scoped to the task. No incidental refactors, mass renames, formatting sweeps, dependency bumps, or new abstractions unless required.
- Read affected usages, call-sites, tests, configs, docs, and contracts before changing an owner symbol or public behavior.
- Use repository-native commands and scripts. Do not invent commands, paths, APIs, fields, flags, versions, or dependency behavior.
- Never claim a check passed unless it ran in this session. State skipped checks and blockers plainly.
- Preserve behavior unless the task explicitly requires a behavior change.

## Engineering invariants

- Keep one source of truth per business rule, invariant, and state transition.
- Do not duplicate domain logic across layers.
- Validate inputs at system boundaries.
- Prefer explicit data flow, ownership, control flow, and failure handling over hidden logic.
- Do not add hidden fallbacks, silent retries, error suppression, speculative flags, compatibility branches, or extension points unless required and safe.
- Remove replaced or dead logic unless backward compatibility requires both paths.
- Use least privilege, prevent secret leakage, define error boundaries, and make production failures diagnosable.

## Product and UI rules

- Reuse existing components, tokens, typography, spacing, icons, motion, copy patterns, and interaction patterns.
- Cover relevant empty, loading, success, error, disabled, no-access, accessibility, privacy, analytics/observability, and release-impact states.
- Do not expose raw internal states, stack traces, implementation details, or diagnostic noise to users unless explicitly required.
- Use concise user-facing copy with clear labels, actions, and error messages.

## Required execution sequence for non-trivial changes

1. Identify behavior to change and behavior to preserve.
2. Determine affected system areas and delivery surfaces.
3. Locate contract owners and sources of truth.
4. Read affected usages, call-sites, tests, config, and docs.
5. Apply the change at the owning layer.
6. Update only affected tests/docs/copy.
7. Re-check compatibility from the changed symbol outward.
8. Run repository-native validation when available.

## DoD

- Acceptance criteria are met without unnecessary behavior changes.
- Contracts are preserved or formally updated.
- Diff is sufficient, scoped, and follows repository patterns.
- Affected usages, call-sites, tests, config, and docs were checked.
- Repository-native checks were run, or unavailable checks are listed.
- User-facing changes cover relevant UX states, copy, accessibility, observability, security/privacy, and release impact.
- UI changes use the existing design system or a coherent extension.
- If frontend behavior changed and preview tooling is available, attach a Playwright preview/screenshot; otherwise state the limitation.
- Final response is in Russian and includes: what changed, key files, verification, manual checks, assumptions/risks, tests.
