# Continuous activities and feedback implementation plan

> For agentic workers: implement the approved spec, use focused parallel work only for independent files. Owner requires one final isolated acceptance pass, no per-step test runs and no rollback engineering.

Goal: concrete time-consistent daily experiences, lean ordinary replies, and safe scheduled assessment repair.

Architecture: SQLite project/feedback receipts; query-time visibility; source-bound two-phase main entry; existing native jobs.

Tech: Python3.10+, SQLite, Node ESM, standalone HTML.

Spec: ../specs/2026-11-06-lived-activities-feedback.md

## Global constraints

- Preserve six layers, full48 same host model, original event identity/time and one sticker draw.
- Never publish private source text/persona/identifiers or invent browsing evidence.
- No new heartbeat, no main-chat debug messages, no synthetic production probes.
- Late repair does not replay original send, relationships or expectations; successful appraisals never apply twice.

## Tasks

- [x] 1. Add activity project store/API, sealed stage projection, interrupt/revise, artifacts and regression cases. Integrate tick/context without changing phone intent behavior.
- [x] 2. Add lean source-bound prepare/commit path and regression cases; preserve stale-source checks/full48/reading completion and legacy adapters.
- [x] 3. Add bounded feedback work/repair receipts with original-time decay and no output/send side effects. Integrate current-schema life appraisal prompts and panel observability.
- [x] 4. Update canonical task/deployment/onboarding/inheritance docs, version/provenance and one final isolated test pass plus wheel check. Inspect diff and fix concrete failures only.
- [ ] 5. Publish and independently verify GitHub; deploy using Muse debug sidechat, update/read back actual existing jobs and live hashes; private architecture-lock snapshot.

## Review focus

Future drafts must not enter recall/context/panel. Real web observations cannot be prewritten. Repeated/late corrections cannot amplify mood. Rapid consecutive user messages cannot reuse stale context. Optional features and legacy roots remain compatible. Each is covered by the corresponding isolated regression cases.

## Execution ledger

2026-11-06: existing isolated linked worktree is clean at 451ed42, branch feat/optional-social-reading-v070. Owner's already-approved design and single-final-test instruction supersede skill reapproval and red/green repetition. Existing native task API is inside Muse; Codex automation tool cannot edit Muse tasks, so use Muse's actual scheduler through authorized debug communication.

Final acceptance: new behavior + legacy Python + Node paths passed. Targeted fixture corrections closed Windows SQLite handles and aligned legacy news fixture gate/expiry clocks; only failed groups were rerun. Fresh static review fixed the activity name compatibility alias. Wheel verification follows before publish. No production synthetic turns. Cleanup of six owned failed-fixture directories was denied by automatic approval; they remain outside the repository.
