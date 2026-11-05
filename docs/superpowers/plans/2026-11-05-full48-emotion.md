# Full48 implementation plan

Spec: ../specs/2026-11-05-full48-emotion.md. User approved inline implementation.
Existing linked worktree is clean at cfb50e5; retain it, no new worktree.

1. Add `muse_ext/emotion_full48.py`: strict normalization, complete template,
   bounded per-event vectors, atomic full-state receipt, six group summaries.
   Integrate catalog validation and companion state without changing sparse v2.
2. Extend the main adapter to return the complete current template, validation
   errors and an explicit pipeline success flag. Preserve the one-draw fallback.
   Project the actual full48 receipt and per-label deltas into the panel.
3. Add isolated real-runtime regressions for 48-field completeness, wrong field
   diagnostics, budget/gain/decay semantics, same-group mixed feelings, zero
   groups, replay and invalid-then-corrected submissions. Run the assembled
   acceptance suites and installed-wheel check once; fix failures narrowly.
4. Update canonical protocol/onboarding/version/provenance; review the final
   diff, publish portable changes, deploy exact hashes via Muse and update the
   private vault code lock. Read back actual state; no live synthetic probes.

Review focus: incomplete vectors cannot masquerade as all-zero evaluations;
budget scaling does not cancel gain; label decreases are selected by absolute
change; repeated input IDs do not apply twice; wrong field names produce useful
errors and corrected submissions reuse the existing draw.
