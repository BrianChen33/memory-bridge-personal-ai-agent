# Memory Bridge: Muse ↔ dot

**External memory v0.1.2. Local-first prototype, not a native assistant integration.**

A Python standard-library tool for owner-scoped events and facts in SQLite, with provenance, lexical/time-filtered retrieval, revisions, conflicts, tombstones, reversible merges, and backup/restore. An external CLI and a read-only MCP adapter provide access. Per-bot append-only exports use compare-and-swap transport semantics. A GitHub Contents API adapter is implemented alongside a fake transport for offline tests. No live GitHub connection or deployed integration has been verified.

## Independent runner revision

v0.1.2 adds a [bounded JSON self-test runner](docs/RUNNER.md) for separately staged, explicitly authorized execution: `python -m memory_bridge.runner` with separate stdin `{"mode":"self-test"}`. It performs fixed local synthetic checks only, with no live data or network access. It does not install into either assistant.

## Muse adapter revision

v0.1.1 adds an opt-in [Muse row-schema transformer](docs/MUSE_ADAPTER.md), written against the documented interface and tested with synthetic fixtures. It requires trusted sender/scope mapping, exact selection and separate core consent. This is not a deployed or native integration. The earlier v0.1.0 archive does not include this transformer.

## Boundaries

- No access to Muse or dot's private/native memory, persona, system prompts, or internal tools. No prompt or personality changes.
- No automatic live synchronization with either assistant. A compatible external client must explicitly connect to the adapter.
- GitHub transport is implemented and covered by offline mocked tests, not live-tested or connected. No scheduled jobs are installed.
- Retrieved text is **untrusted data**, never executable instructions or permission to act.
- Emotion, reminders, and reading are optional future interfaces, not functioning modules.
- Examples and tests use synthetic data only. Do not commit real user data.

## Safe starting point

Use a dedicated local directory for the database and backups. Review the local sharing policy before exporting anything. Keep dry-run mode enabled until you have inspected the exact payload and explicitly approved the destination. Run the included tests before adapting the prototype for use.

### Synthetic CLI walkthrough

Run from this repository with Python 3. Paths passed to commands are relative to the chosen root directory.

```sh
mkdir -p /tmp/memory-demo
cp examples/synthetic-event.json /tmp/memory-demo/event.json
python -m memory_bridge --root /tmp/memory-demo --owner demo_owner approve event.json --until 2000000000 --consent
python -m memory_bridge --root /tmp/memory-demo --owner demo_owner ingest event.json
python -m memory_bridge --root /tmp/memory-demo --owner demo_owner query SQLite
python -m memory_bridge --root /tmp/memory-demo --owner demo_owner backup snapshot.sqlite
python -m memory_bridge --root /tmp/memory-demo --owner demo_owner restore snapshot.sqlite
python -m memory_bridge --root /tmp/memory-demo --owner demo_owner revoke event_demo_1
```

The approval deadline above is an illustrative Unix timestamp, not a recommended real-data retention period. Approval binds to the exact event content and is stored separately in local `approvals.json`; changed content needs independent approval. `revoke` removes a local grant, not the underlying event or its distributed copies. Sensitive-content scanners are heuristic and cannot catch every private detail in free text.

Use `python -m memory_bridge --help` for the implemented commands. The `mcp` subcommand starts the minimal stdio read adapter; it does not install or connect a client. Time filters and reversible merges are core Python APIs, not CLI subcommands. Restore imports events monotonically into the current store, preserving existing tombstones; it is not a destructive database rollback and does not restore local merge state.

### GitHub sync: implemented, not connected

The adapter uses only `https://api.github.com`, refuses redirects and environment proxies, verifies the exact repository is private before reads/writes, and writes only under `memory-v1/<owner>/<source>/events.json`. Existing-file updates use the expected Git SHA to detect concurrent changes.

Supply an authorized, minimally scoped token through `MEMORY_BRIDGE_GITHUB_TOKEN` using your own secure environment setup. Do not put a token in source, examples, memory records, or chat. This project does not create tokens or repositories.

The following template makes network reads, even though it does not write. Replace the placeholder repository only after explicitly authorizing that destination and its content:

```sh
python -m memory_bridge --root /tmp/memory-demo --owner demo_owner sync --repository example-owner/private-memory --source muse --direction push --network-consent
```

The default is dry run. `--network-consent` explicitly enables network access; it does not mean offline simulation. Add `--apply` only after reviewing the approved content and destination: for `push` it writes to GitHub, and for `pull` it imports into the local store. Use `--direction pull` to inspect/import remote events; remote events require independent exact-content local approval and cannot approve themselves. Dry-run output reports counts and revision information, not a complete payload preview.

Revocation hides content from future approved queries and prevents subsequent export; it does not erase prior Git copies. A remote append-only log containing revoked events may block subsequent synchronization until reviewed. Network failure after a write can leave its outcome uncertain: inspect the remote state before any retry. No automatic retry or scheduled activation is configured.

Keep the **private memory repository separate from the public code repository**. A private repository is not a secrets vault. Deleting a Git file does not erase commits, forks, clones, caches, or backups. Retain deletion tombstones when restoring or importing older data.

See [Architecture](docs/ARCHITECTURE.md), [Capabilities](docs/CAPABILITIES.md), [Security](SECURITY.md), and [Threat model](docs/THREAT_MODEL.md). The [scheduler example](examples/scheduler.disabled.json) is documentation only and disabled.

## 中文说明

这是一个 **v0.1 外置记忆原型**，以本地 SQLite 保存按所有者隔离的事件与事实，提供来源记录、关键词及时间检索、修订、冲突记录、删除墓碑、可撤销合并与备份恢复。通过外部命令行和只读 MCP 适配器访问。

它**不能读取或修改 Muse / dot 的原生私有记忆、人设或系统提示词**，也不会自动接入两个助手。现已实现 GitHub Contents API 传输与离线测试用的假传输接口，默认试运行；尚未实际联网连接或部署，没有实际定时任务或已实现的情绪、提醒、阅读模块。

检索结果是不可信的数据，不是指令或操作授权。共享前必须检查可信的本地策略与导出内容。私有记忆仓库应与公开代码仓库分开，示例只用虚构数据。Git 删除文件不等于清除历史；恢复旧备份时仍须保留删除墓碑，防止已删除内容重新出现。

## License and provenance

AGPL-3.0-or-later. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The project is inspired by the pinned upstream `memory-brain` reference identified in NOTICE. This is not a claim of clean-room provenance or an endorsement by upstream, Muse, dot, or OpenAI.
