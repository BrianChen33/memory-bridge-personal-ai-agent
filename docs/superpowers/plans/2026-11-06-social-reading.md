# Optional social reading implementation plan

> For agentic workers: use superpowers:executing-plans inline. User requested a
> fast delivery and one final isolated acceptance; do not repeat broad suites.

Goal: opt-in native-browser reading, source-gated onboarding, evolving speech
habits, reusable video-provider interfaces and an extensions panel card.
Spec: ../specs/2026-11-06-social-reading.md
Tech: standard-library Python/SQLite, existing single-file HTML, no new service.

## Constraints and review focus

- Empty/unverified/revoked allowlists must fail closed at plan and commit.
- Plugin absence/failure must not break ordinary messages or core-only installs.
- Partial pages/metadata cannot be called complete reading or video observation.
- Replays cannot add habits, observed events or emotional changes twice.
- Candidate language has no authority over persona/permissions and stays scoped.
- Actual deploy uses exact code hashes and preserves private host overrides.

## Tasks

- [x] Verify original npm/repository behavior and native browser tool boundaries;
  record real results without retaining cookies or probe data in production.
- [x] Add muse_ext/plugins.py management/loading/context/panel API; wire the
  companion dispatcher, prepare projection, CLI and backup allowlist. Install is
  explicit from a local trusted source manifest; initialize never installs one.
- [x] Build separate plugins/social-reading package: source identity/verification,
  bounded reader leases/receipts/sampling/cache, model reflections and durable
  evidence-linked candidate/trial/mature speech habits. Add disabled provider
  descriptors for Douyin/Bilibili with honest video observation boundaries.
- [x] Replace panel-update card with plugin projection/details, keep refresh
  details in About, preserve compact responsive art/layout.
- [x] Add meaningful isolated regressions for source gates, malicious URLs,
  partial coverage, replay, revocation, style promotion/correction, disabled
  providers and core-only/optional installation outside the checkout.
- [x] Write canonical installation, browser protocol, source onboarding,
  inheritance and future video plan; update version/provenance and third-party
  attribution. One assembled test_all + check_wheel; targeted fixes only.
- [ ] One final review, publish exact commit, deploy without overwriting host
  customizations, replace panel card, ask owner sources via Muse after install,
  and verify remote private architecture lock. Do not activate an empty source set.

## Progress

Existing linked worktree reused at 8055a72; clean prior release accepted.
No new baseline suite: user explicitly requested one final assembled acceptance.
Source onboarding is Muse's post-install responsibility; Codex does not collect
the permanent allowlist during development (user correction incorporated).

Final acceptance: old Python suites passed;8 new tests exposed a Windows newline-copy bug. Byte-copy install fixed it;10 targeted plugin checks now pass, including4 final-review findings (nullable fields, exact URL identity, metadata-only dedup, interrupted registration repair). Remaining runtime/Node suites passed; installed core+optional install outside checkout passed. No second broad acceptance.

Cleanup limitation: automatic command approval rejected deleting8 owned failed-test directories under Windows Temp, even after exact path verification. No bypass attempted. Local UI preview cleanup remains pending.

UI acceptance: desktop and375px portrait card/details verified, no horizontal overflow; viewport restored and preview server stopped. Existing emotion task uses pending to bind actual document/event IDs, not guessed IDs; its interest/share case passed after this narrow adapter addition.
