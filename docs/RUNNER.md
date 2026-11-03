# Independent self-test runner / 独立自检入口

v0.1.2 adds `python -m memory_bridge.runner`. This is a **self-test-only** JSON stdin/stdout entrypoint for a separately staged copy of this package. It does not install itself into Muse, change main/QQ code, read production databases, capture chats, modify personas, connect dot, or contact GitHub.

## Invocation contract

- Command: `python3 -m memory_bridge.runner`
- Working directory: an independently unpacked release directory.
- Separate stdin, closed after this JSON value: `{"mode":"self-test"}`
- Arguments: none. No paths, shell commands, credentials or other fields are accepted.
- Output: one JSON summary, no fixture text, local paths or input echoes.
- Exit 0 means the synthetic checks passed. Nonzero means failure; inspect the fixed error code.

The runner bounds stdin to 65,536 bytes and rejects malformed JSON, duplicate keys, trailing JSON values, unsupported modes and unknown fields. Its five-second total budget includes waiting for stdin EOF. It starts a fixed Python child worker with no shell and no stdin; on timeout it terminates and reaps that child. A parent-owned real temporary directory contains the synthetic databases and canary and is cleaned after worker termination or success. No user-supplied directory or command can enter the worker protocol.

The deadline is an application watchdog, not a sandbox or a hard real-time OS guarantee. OS suspension, uninterruptible kernel I/O, process termination or host failure can prevent ordinary cleanup. All normal success and tested timeout paths clean their temporary directories. The worker performs only fixed local synthetic operations and creates no child processes itself.

## What the checks establish

The summary covers denial before exact approval, dry-run nonmutation, fake-transport replica deduplication, untrusted retrieval tagging, deletion without resurrection, revocation and an unchanged synthetic persona canary. Fixed synthetic approvals are for the embedded test facts only; they never authorize production sharing.

A passing result verifies this package in that Python environment. It does not prove either real assistant is integrated or that private synchronization works. There is no live conversion, automatic capture, production-data import, scheduler activation or automatic approval mode.

## Safe staging plan

Use a new directory such as `~/memory-bridge-staging/v0.1.2/`, not an existing Muse project or runtime directory. Verify the release files before execution. If the environment supplies a native command tool with separate stdin, send the command and JSON stdin separately; do not construct a shell interpolation from chat content. Running newly staged code on a different environment still requires that environment's applicable authorization.

If a tool returns a background job identifier, poll that exact job to completion and inspect both exit status and JSON. The tool returning early is not the runner's timeout. A `timeout` error is terminal for that run; inspect the environment rather than retrying indefinitely.

中文：这是单独暂存目录中的合成数据自检，不接入实际 Muse/dot，不读取生产库或人设，不启用网络或定时同步。命令与 stdin 分开提供，stdin 关闭后解析；总预算五秒，超时终止子进程并清理自建临时目录。通过只表示此 Python 环境能够运行自检，不代表真实助手已经完成集成。
