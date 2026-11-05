# Full48 emotion and reliable assessment receipts

Approved by the user: every reply model considers all 48 emotions, persists all
48 signed changes, and displays one representative per existing group, chosen
by the largest absolute actual event delta. Zero-change groups stay unchanged;
do not force novelty, positive/negative balance, or changes in every group.

At the current reference gain 1.5, ordinary conversations usually change a
relevant emotion by 0.01–0.03; salient contextual events can reach 0.1–0.2.
These are ranges, not required minimums. Preserve the user's gain and apply it
once. Calibrate fixed raw caps against reference gain 1.5; future gain changes
still proportionally affect reactions. Bound total absolute change as well as
individual labels so filling 48 fields cannot amplify an ordinary message.

Keep envelope version 2 and the existing vocabulary. Add the strict
`format=full48-v1` with `emotion_deltas` containing exactly all 48 labels,
`impact=ordinary|salient`, PAD delta, and the canonical appraisal structure.
Generate a complete template at context time. Keep sparse v2 compatibility for
existing channel adapters; do not rewrite QQ/WeChat transports or historical
assessments. New main-chat submissions use full48. Missing/invalid is explicit,
includes a field-level diagnostic, and cannot be reported as successful.

Persist raw/bounded/applied vectors, the decayed before state, after state,
budget scale, gain and group summaries atomically. Source identity, full text,
actual timestamps, one-draw idempotency, decay and scope boundaries remain.
Do not conflate decay with event-induced changes. Retry a rejected assessment
using the same event and draw. Never refill historical invalid turns as though
they succeeded before the correction.

Project the last actual assessment into the existing offline panel. Keep all
48 details and six summaries. Reuse the current reply model; no extra model or
new periodic task. Preserve persona, current state, settings and media policy.

Deploy and read back exact hashes in the Muse system-debug sidechat. Publish
portable code/docs and update the private architecture lock. One final isolated
acceptance pass; no synthetic production events or new rollback engineering.
