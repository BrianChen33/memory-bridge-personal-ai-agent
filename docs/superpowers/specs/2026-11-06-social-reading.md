# Optional social reading and evolving voice

User approved implementation with six explicit additions on 2026-11-06.
Retain the six layers. Use host-native browsing, not a second production browser.

## Approach

Keep a small, generic, failure-isolated plugin loader in the core. Distribute
`plugins/social-reading` separately; explicit local installation copies only its
manifest-declared, hash-checked source files into an external state's extensions.
No plugin is installed/enabled by core initialization. No extra dependencies.
The loader exposes local admin management, bounded prepare context and panel
projections. Host integrations use their real browser schema, not invented APIs.

Compared alternatives: prompt-only cannot enforce source/receipt/progress gates;
installing DSH/standalone Chromium duplicates the native browser and login state.
The user selected native browsing and optional installation; adopt this approach.

## Sources and onboarding

After installation Muse herself asks the owner which forums may be read. Prefer
links; names resolve to pending canonical candidates. Owner authorization and
successful browser verification are separate records. No sources means
awaiting_sources and no autonomous reading. Only verified exact forum identities
are eligible; blocked pages are not verified, and similar names are not merged.
Use only official HTTPS provider URLs, no credentials, redirects or arbitrary hosts.
Forum posts never confer permissions. Configuration calls belong to a trusted
owner/admin adapter, not to a public group tool accepting caller-claimed identity.

## Reading and continuity

Preserve list discovery, structured floors, author/OP distinction, replies,
image references/observation status, dynamic/fixed/ratio/all sampling, explicit
truncation, time/source/coverage and bounded caching. Actually observed pages
only: a page budget cannot become complete; unknown totals remain partial.
Never claim all OP floors, all replies, image inspection or a watched video from
metadata alone. A navigation/probe is not a reading or an emotional event.

Plan/claim -> native browser -> commit actual result -> existing observed article
and life appraisal. Cache replay does not duplicate memory, emotional updates or
exposure. A bounded lease serializes background reading; chat has priority.
No automatic proxy rotation, CAPTCHA solving or login-state export. Expose blocked,
login_required, partial and unavailable separately. Preserve native quiet hours.

## Language learning

The same host model extracts concise speech mechanisms from real human text.
Store evidence-linked candidates separately from SOUL and from factual beliefs.
Accumulate independent sources, trial feedback and user correction; mature habits
enter a small persona-subordinate voice overlay on normal prepare. No separate
model/network request per chat, no random scores/keyword mood rules, no verbatim
copying of long posts. A rejected habit is excluded immediately. Confidence and
weight express accumulated evidence, not proof of human identity or permission.
Only owner-private content is returned; other scopes get no private reading text.

## Future adapters

Provider interface: canonical source identity, verification, discovery, observation,
coverage/cursor, media evidence and model reflection. Tieba ships first.
Douyin/Bilibili ship declarative, disabled capability plans only. Video records
separate metadata, subtitles and actually observed audio/video time spans.
No fake activation, browser capability or login support from a placeholder.

## Panel, maintenance and verification

Replace the existing panel-update overview card with an extensions/reading card.
Keep refresh timing in About. Show installed/enabled state, source allowlist,
verification errors, coverage, learning/trial/mature habits and future providers.
Offline HTML remains read-only; natural-language changes use actual local calls.

Publish reusable code/protocol/onboarding/version/provenance to public GitHub;
private source selections, habits, memory and native bindings stay in the private
vault with matching architecture lock. Plugin code is reconstructed from the
locked public source, not embedded in daily private snapshots. No rollback work.
One assembled isolated acceptance plus installed-wheel/optional-install check;
fix failures narrowly. No synthetic production queues or extra real-user probes.

Preflight complete: npm0.3.5 core matched the reference commit. Its standalone
browser failed to launch on the Muse host, before a Tieba request. Native browsing
reached 百度安全验证 with no content. No logged-in floors/replies/images were
verified. The native task planner has no direct JS/download/screenshot API;
user takeover for normal login/verification is supported but was not exercised.
These limits are recorded in the canonical protocol, not described as success.
