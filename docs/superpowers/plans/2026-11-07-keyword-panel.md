# Compact reading vocabulary panel

Owner requested implementation: group catchphrases by learning status and show
only keywords. Preserve learned data and growth rules. Existing isolated checkout
is clean at 4f5e8c5; implement inline using executing-plans.

## Design and plan

- [x] Replace expanded habit rows with keyword chips grouped as trial, mature,
  reference, candidate, rejected and unknown. Use the existing snapshot; counts
  refer to supplied snapshot records, not an invented database-wide total.
- [x] Add local keyword search, status filters and 24-item pagination. Bound
  the list height and wrap controls for portrait/landscape. Do not render
  meanings, examples, sources or usage details, including tooltips.
- [x] Update HOME_PANEL/deployment/inheritance notes, package version/provenance
  and release checksums. Keep runtime2.7.1/plugin0.4.0 and all live settings.
- [x] One final isolated acceptance: existing test_all and wheel checks plus
  desktop/mobile visual checks with synthetic long lists; no production probes.
  Reversible layout work needs no new implementation-mirroring test suite.
- [ ] One final read-only review, publish and verify remote SHA, replace only
  the Muse HTML template and vault version helper, silently regenerate the same
  Library HTML and update the private architecture lock. No reinstall or cron.

## Review focus

- Unknown/empty states, Unicode/long keywords, HTML-like text and zero results.
- Page changes/filter resets and honest counts on the bounded snapshot.
- No mutation of emotions, habits, permissions, sticker draws or other sections.
- No external dependencies, model calls or regenerated private examples in code.

## Ledger

2026-11-07: user supplied the layout and explicitly asked for less debug/testing;
proceed without another design approval or per-step test cycle.

Final acceptance: 456 Python tests and13 Node tests passed; wheel accepted outside
checkout. Synthetic180-word desktop/375px checks covered classification, paging,
search, literal HTML-like text and long-label clipping. One final read-only
review found no blockers. Publication/host readback are recorded separately.
