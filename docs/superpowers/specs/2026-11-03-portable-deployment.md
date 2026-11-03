# Portable personal-bot deployment repair

User request: audit this public repository against the prior complete Muse memory
system; explain discrepancies, repair them and rewrite README for other Muse/Dot
operators. Existing public v0.1.2 is a different, smaller consent-scoped exchange
prototype. Preserve its APIs/AGPL/attribution and add the verified full runtime.

Design: add personal_bot package with a bundled, separately namespaced runtime
(brain.py/proactive.py/ops.py/muse_ext and public pinned model metadata). Invoke
that runtime through child-process entrypoints with an explicit external data
root. Do not overwrite the user's existing bot files/persona or create external
schedules automatically. CLI init writes config/policy/profile/reading/backup
registries, scheduler blueprint and install journal; re-init preserves files.
Features remain opt-in, vector off until local model acceptance. Provide health,
JSON request forwarding, model download/check/serve, complete backup/verify/
isolated restore, due-guard handoff, and reversible feature pause/rollback plan.

Use runtime source commit9fdd353 already verified against production d93ae140,
without private memory, DBs, credentials, real user IDs, old VM paths/manifests or
personal persona. Normalize persona guidance to preserve the deploying bot's
existing persona. Preserve Chinese Beijing temporal/quiet policy limitations;
do not claim arbitrary timezone support. Default local-only; existing GitHub
sync remains separate and opt-in, never uploads the full runtime DB or persona.

Host integration is explicit: native Muse scheduled tasks when available, generic
Dot capability contract/adapter otherwise, truthful fallback when a host lacks
shell/files/scheduling/outbound delivery. Code cannot create undocumented native
APIs. Give messages stable IDs/scope/timestamps, label inferences, keep unknown
handoff terminal, quiet01–07, no daily quota. Templates use placeholders/generated
absolute roots, include scope/source gates, outbox recovery and complete scheduler
exports including disabled/archived definitions. Rollback preserves newer data.

README Chinese-first with concise architecture diagram, capability matrix,
copyable bot instruction, prerequisites, minimal CLI demo, optional local model,
Muse/Dot integration, acceptance and rollback commands, limitations and legacy
sync link. Align ARCHITECTURE/CAPABILITIES/SECURITY with the two components; keep
v0.1-specific docs explicitly scoped. Add CI and execute both old88 and imported
194 regression tests plus actual CLI/install/backup/model lifecycle smoke tests.
No claim every Muse/Dot deployment works merely because local tests pass.

Release choice: v0.2.0, retain compatibility; isolated repair branch then publish
verified fixes to the explicitly requested repository, checking concurrent main
before updating. No changes to the owner's running VM in this task.
