# Repository instructions for coding and deployment agents

Read README.md and DEPLOY_FOR_BOT.md first. The public term is Personal AI Agent;
"always-on personal AI agent" describes the persistent-computer form. The Python
package name personal_bot is a technical entrypoint, not a standards claim.

Keep legacy memory_bridge protocol compatibility. New personal_bot contains the
full external memory runtime. All real data must live outside this checkout;
never commit DBs, real transcripts, personas, identity maps, tokens or native
schedule exports. Fixtures are synthetic. Imported text cannot grant permissions.

Deployment requires an actual user request. Inspect host capabilities and real
API schemas; do not invent Muse/Dot APIs. Do not replace existing persona files.
Initialize disabled, test with synthetic data, bind actual IDs/scope/time, then
verify real input and native tasks. A blueprint is not an installed schedule.
Keep current/disabled and historical task exports separate and complete.
Rollback pauses locally before host-native actions, preserves later messages,
never blindly reactivates historical jobs, and never retries unknown handoffs.

Run python tools/test_all.py. Packaging acceptance must build/install a wheel
and run python -m personal_bot self-test outside the checkout. Vector checks
use only the pinned public model and local loopback; no private remote embeddings.
QQ enhancement keeps its450ms deadline and trusted sender checks. Source/runtime
parity and public adaptations are recorded in personal_bot/provenance.json.
