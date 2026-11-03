# Audit and v0.2 repair

Baseline main033d739 contained v0.1.2 consent-scoped exchange only. It explicitly
lacked emotion/reminders/reading/semantic retrieval/native task deployment and
only backed up its separate SQLite event store. That did not match the complete
Muse system discussed with the owner. README now distinguishes both components.

Imported source9fdd353 with provenance hashes; wrapper invokes standalone runtime
in a controlled subprocess with explicit external data root. Preserved old
88 tests/protocol. New init/CLI/restore/relocate/pause tests observed failures
before implementation; QQ roots and generic persona regressions also RED→GREEN.
Builder check addressed full code backups, code/data QQ split, disabled schedules,
installed-wheel testing, truthful host capability boundaries and old quiet-rule
conflicts. No old private VM adapter docs/manifests/persona were published.

User steering: use researched conventional category names. Official Meta calls
Muse personal AI agent; official OpenAI Learn calls dot always-on agent. README
uses Personal AI Agent and describes persistent-computer form as always-on;
TERMINOLOGY cites primary sources and does not invent a standards claim.

Baseline Windows88 had one symlink privilege error, now an explicit host skip;
Linux CI retains full check. Older Windows Python fchmod absence reproduced and
fixed without changing local event grant policy. No data from running Muse VM
or native schedule exports is present in this public source change.

Pending: full suite, installed wheel outside checkout, real optional-model smoke,
fresh final review, atomic remote publication and readback.


Final review: three Important findings reproduced RED→GREEN in one pass:
1.native tree registrations survive relocate and a second full backup;
2.corrupt DB cannot prevent local pause/epoch fencing;
3.referenced host install manifests/original blobs are included and recovered
without original state; targets rebind only to isolated native copies.
CI source-shadowing finding regraded Important for this deployment goal; replaced
checkout-only selftest with an isolated wheel install/outside-checkout acceptance.
No remaining review findings deferred. Full300Python checks (2Windows symlink
privilege skips)+7Node passed. Core module source still has its194 regressions.
Installed wheel accepted outside checkout; optional pinned real model512dim
related.423/unrelated.178 and actual semantic recall succeeded,2vectors indexed,
wrapper336ms in this local run. Closed the verified owned test encoder and
confirmed18765 had no listener afterwards.

Ruling: preserve legacy exchange API and add a separate complete runtime rather
than replacing consent-scoped sync — preserves existing consumers — cost if
wrong: two documented entrypoints to maintain. No native Dot deployment is
claimed without that host's actual capabilities and acceptance. Public category
uses existing official terms, not an invented industry standard.

Pending: expected-head GitHub publication and remote tree/README readback.
