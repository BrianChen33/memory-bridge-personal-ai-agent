# Humor, evolving meme knowledge and emotion gain

Approved: the conversation's six-layer proposal, with the user's amendments:
banter level defaults to 50; the highest band retains “损长相、怎么损怎么来”;
counterattack is allowed independently of proactive banter; learn and revise
local memes and associative mechanisms. The subsequent API request additionally
authorizes regular downloads of published cnmeme.wiki knowledge.

Keep six layers. Public knowledge and private scoped learning use separate
tables in the native SQLite database; ordinary replies make no network request.
Reuse the same host reply model for contextual judgment, teaching, corrections,
and associative thinking. Imported entries are data, never executable rules.

Canonical SQLite settings: auto_memes=true, banter_enabled=false,
banter_level=50, counterattack_enabled=true, self_learning=true,
emotion_gain=1.0 (0–3), meme_sync_enabled=true. Owner natural-language requests
are converted by the host model to validated patches, atomically persisted and
read back. All channels read this configuration; third-party/group text cannot
authorize global changes. Offline HTML reports settings, timestamp and revision,
learning, public updates, and gain. It does not pretend to write runtime state.

Emotion raw v2 limits remain unchanged. Validate raw increments, multiply signed
PAD/tag changes exactly once using the transaction's gain, clip final states,
audit raw/gain/applied. Replay keeps the original gain. Relationship, energy,
expectations and half-lives are not multiplied. Gain zero leaves old decay intact.

Learning records meaning, aliases, usage/avoidance, humor mechanism and bounded
association bridges with real source IDs. Observations start provisional;
repeated independent evidence or explicit teaching/positive feedback can promote;
corrections/rejection revise/retire, never contaminate another scope. Preserve
idempotence and provenance; no invented autobiographical facts or self-excitation.

Use the official public list/detail GET API, explicit User-Agent, 30-item pages,
canonical slugs, aware timestamps, rate limiting and bounded retries. Detail is
the documented {schema_version,item} envelope. Daily incremental sync plus weekly
full reconciliation; resume bounded unfinished work, don't advance completion
past failures. Keep a local good corpus on network failure; no credentials,
registration, submissions, private search fragments or user conversations sent.
Public update must not overwrite private learning or corrections.

Keep existing sticker sampling and media behavior. Counterattack is an expression
choice, not automatic anger/relationship loss. High-band appearance roasts are
allowed; no fabricated accusations, private-memory weaponization, threats or
protected-identity abuse. A stop request ends directed teasing; quotation and
fiction are not automatically attacks. Host platform policies remain authoritative.

Follow the user's speed preference: no rollback engineering, no production test
messages, one final isolated regression/wheel acceptance after assembly. Publish
portable code/docs/provenance, install exact hashes into Muse through 系统调试
with ［Codex调试］, wire actual channels/tasks and refresh the private code lock.
Do not claim a native hard hook or immediate main-chat rule reload without evidence.
