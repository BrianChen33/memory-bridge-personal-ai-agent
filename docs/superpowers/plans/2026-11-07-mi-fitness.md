# Restricted Mi Fitness integration

> Implement inline with executing-plans. The user requested direct execution,
> one final isolated acceptance, no rollback work and no repeated broad tests.

**Goal:** Local QR authorization, encrypted credential delivery to the host,
and owner-private sleep/activity context without slowing ordinary replies.

**Architecture:** An explicitly installed optional plugin reads a tiny local
projection through the existing plugin_context hook. A separate Python3.12+
worker uses pinned mifit0.4.0 with a fixed sleep/steps/activity/workouts allowlist.
Credentials, daily records and receipts live outside the brain and backup trees.
The current life30m task checks an hourly sync gate; no additional scheduler.

**Authorized scope:** Sleep duration/stages/times, steps, activity and workout
summaries only. No independent heart rate, SpO2, stress, weight, profile,
relatives, raw requests or GPS. Upstream credentials cannot enforce these fine
scopes: this boundary is implemented in the adapter, not claimed as vendor OAuth.

**Integration:** Existing reply model can use compact observations to care about
the owner, without assigning owner measurements to the bot's own mood/energy.
First sync establishes a silent baseline; new sleep/workouts become once-only
care candidates in the existing life task. Quiet01-07, real receipts, unknown
does not auto-resend. No medical conclusions or fabricated missing measurements.

## Tasks

- [x] Add optional plugin shim, bounded worker, sealed handoff and local QR tool.
- [x] Add focused isolated coverage for owner scope, field restriction, missing
      values, cache-only context, hourly gating, quiet/deduplicated care and
      authenticated one-time credential import. Run test_all and wheel once.
- [ ] Update onboarding/inheritance/deployment/version/provenance, seal manifest,
      publish public code and independently verify the remote commit.
- [ ] Receive host public key; authorize locally and upload ciphertext only.
      Deploy fixed sources, bind existing life task, confirm cloud readings and
      scope/backup exclusion, update private architecture lock, clean temporaries.

## Decisions and evidence

- Existing linked worktree muse-expression-v063 is clean at fc2d340; reuse it.
- The fixed deployment description and execution are already user-authorized.
- Preserve core runtime2.7.1, reading plugin0.4.0 and the current persona/channels.
- Raw health stores and login material stay out of both GitHub repositories.
  Ordinary chat/feedback can contain health summaries, so foreground context and
  care remain gated until the owner explicitly approves that existing private
  memory/backup flow. Public tests use synthetic data; no production test sends.
- Final isolated pass:463 Python and13 Node tests passed, wheel accepted outside
  checkout. Single read-only review found newest-workout selection and an overly
  broad backup-exclusion claim. Two focused regressions failed first; the fixes
  and9 focused cases passed. No second full suite or reviewer.
- Ruling: raw-store exclusion is implemented; blanket native-chat redaction is
  not claimed. Instead a real consent gate blocks health context/care/history
  until the owner chooses whether conversational summaries may enter private
  memory/backup. That question is pending; do not infer approval from silence.
