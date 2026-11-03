# Muse schema adapter / Muse 结构适配器

v0.1.1 adds a pure Python transformation against a documented existing Muse row interface. It does not copy Muse implementation code, execute `brain.py`, read a database, install a hook, or modify Muse. No native dot hook was verified. The external dot-facing access remains the existing read-only MCP tool or explicitly exchanged files.

## API contract: preferred integration boundary

The reviewed interface describes JSON CLI input to `python3 brain.py --root ...`, bounded to 65,536 bytes, with recall/prepare operations. This package **does not invoke that CLI**. `transform_response` accepts one explicitly selected row from a supplied `memories` array. Actual recall rows have exactly:

`id, text, kind, source, event_id, evidence, occurred_at, truncated`.

The trusted caller supplies operation origin (`recall` or `prepare`), independently verified principal, exact request scope, selected numeric row ID and reviewed row digest. Active status comes from that operation contract, not a missing response field or an imported self-assertion. No default owner-private mapping is inferred. A caller must verify it is supplying the result of that authorized request.

Other top-level fields, including mood, emotion, style, event and insights, are never traversed, hashed, serialized or exported. Rows marked truncated are rejected. Optional merged rows (`merge_group`, `original_ids`) are rejected pending explicit reconciliation. Nonselected rows are not transformed or hashed. At most 1,000 memory rows and 65,536 bytes per selected row are accepted.

Only confirmed facts classified explicitly as project facts or task state are candidates. `occurred_at` accepts finite nonnegative Unix seconds, including fractions; shared core timestamps use whole seconds, rounded down. Exact selection still binds the fractional value.

## Optional direct-row helper

The lower-level `transform` helper accepts the explicitly supplied database-shaped fields:

`scope, text, kind, source, event_id, evidence, status, importance, occurred_at, created_at, supersedes, fingerprint`.

It additionally requires a trusted stable `record_id`, distinct from the source event ID. It never reads a database. This stricter helper accepts only `kind=fact`, `evidence=confirmed`, `status=active`, numeric importance 0–1 and finite numeric timestamps. Other database representations require explicit mapping. Superseding records are rejected.

Preferences, relations, episodes, reflections, skills, lessons, emotional/style fields, raw events and unknown row fields are rejected. Category labels do not prove the actual text is safe.

## Trusted selection and identity

`ScopeGrant(principal, scope, owner, audience)` is local trusted configuration, not content from an imported row. `transform` also requires an independently verified principal and the exact reviewed row's `selected_digest`. Computing that digest alone is not authorization. A row cannot approve itself, identify its sender, or supply a default scope mapping. An unmapped group or direct-message scope never falls back to `owner-private`. Explicit group sharing requires its own trusted mapping and applicable permission from the people whose information would be shared.

The adapter creates a **candidate** event only. The scope grant's audience is a local selection constraint, not an exported event field. The caller must intentionally use the same audience when separately approving the candidate. The core's separate exact-event `Policy.approve` remains mandatory before ingest, retrieval or export. Approved content can still be sensitive despite category labels; review the actual text.

Source identities include the principal, exact scope, original source, source event ID and stable memory row ID. Deterministic hashes give each source its own namespace, preventing equal event IDs from different adapters from colliding. Raw scope identifiers, sender identifiers, importance and fingerprint fields are not exported. Hashes are pseudonyms, not anonymization or proof of source authenticity.

Two independent rows under the same source event ID remain distinct. An identical row produces an identical event. Changed content under the same source event identity preserves the fact ID but produces a different event ID. At the same revision, the core quarantines conflicting content. Revision changes require explicit selection and fresh core approval. Source labels are not cryptographically authenticated, and reassigning source event IDs can create a new fact; the trusted selection boundary remains essential.

## Verification status

Synthetic fixtures match the documented field shape. Tests cover explicit consent, inferred/preference rejection, unmapped groups and senders, source collision isolation, deduplication, content conflicts, forbidden fields, bounds and secret-pattern rejection. These are offline contract tests, **not successful runtime integration** with Muse or dot. The adapter never consumes original conversational events or accesses persona files.

中文：此适配器只转换用户明确选中的已确认事实，使用可信的身份及作用域映射，不会将陌生群聊或发送者默认映射为所有者私有记忆。转换后仍须单独批准完整事件。原始聊天、情绪、人设和风格字段不进入共享事件。当前验证仅为虚构数据的离线结构测试，尚未运行或接入实际 Muse / dot。
