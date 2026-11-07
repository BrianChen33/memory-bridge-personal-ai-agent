# Life camera plugin implementation plan

The owner approved the chat design and supplied a private three-view reference.
Implement inline in the existing isolated worktree. Use the approved single
final isolated acceptance pass instead of per-step test runs or production probes.

## Scope

- Package the existing life-camera behavior as the optional `life-camera` plugin.
- Reuse native host image generation and background execution. No external image
  account, extra conversation model, permanent photo schedule or paid API is added.
- Store asset metadata, settings and idempotent generation/delivery jobs in SQLite.
- Require the original identity/style image in each request, with scene-specific
  selfie/rear/mirror composition. Private images stay outside public code.
- Bind automatic plans to released, appraised life events. Explicit requests use
  trusted owner source events. Future project drafts remain sealed.
- Ordinary replies read compact local context only. The life task may enqueue
  work, while a real host background task performs generation and delivery.
- Autonomous defaults are balanced sharing, 30 minute cooldown, one image,
  Shanghai quiet hours 01–07 and no daily count quota. Explicit requests bypass
  the autonomous cooldown/quiet gate, and require the image tool to be available.
- A received image file, successful generation and actual delivery have separate
  receipts. Unknown work is reconciled, never blindly regenerated or resent.

## Tasks

1. Add isolated regressions for opt-in, source/stage binding, references, concurrency,
   cooldown/quiet hours, crashes, receipts, legacy promises and compact panel data.
2. Implement hash-checked reference storage, scene composition and SQLite jobs.
3. Route existing camera entry points through the installed plugin. Preserve the
   legacy path for installations that never installed it. Installed-disabled means off.
4. Add compact read-only camera settings/history to the current panel, documentation,
   plugin manifest, version/provenance, inheritance and release hashes.
5. Run one final isolated test/wheel phase and one focused review. Correct concrete
   failures only. Keep private material and synthetic sends out of production.
6. Push reusable code, verify the remote SHA, prepare the private reference bundle,
   then deploy in Muse 系统调试 with ［Codex调试］ when browser tools are available.

## Review focus

- Concurrent/retried calls keep a single job and a single generation/send claim.
- A changed reference, missing file or future stage never silently weakens identity.
- Ambiguous native work does not freeze unrelated later jobs or replay old images.
- Plugin disable stops photo work despite older presentation-profile settings.
- Private artwork, health values and host identifiers never enter the public kit.

## Progress

Approved chat design is the specification. Existing worktree is already isolated.
Browser automation tools were removed from this session. Owner handoff requested
while code implementation proceeds. No deployment or native async claim yet.

Implementation and one read-only review completed. The final isolated phase covered
482 Python cases with2 platform skips and13 Node cases. Two receipt error-message
assertions were corrected and rechecked locally, and a final scope guard was checked
locally. Remaining suites and wheel acceptance passed. Public release evidence is
reported in the delivery. Host deployment awaits browser tools or the owner upload.
