# Muse / Dot：宿主接入

主术语是个人 AI 智能体，定义及官方来源见 [TERMINOLOGY](TERMINOLOGY.md)。以下是可实现的接口契约，不是 Muse / Dot 的通用官方 SDK。

## 能力与部署位置

Muse 的参考环境可执行本地命令、读写文件并创建原生定时任务。其他账号/版本必须从实际工具 schema 检查，不能假设路径为某个固定 home，也不能把参考实例的任务 ID 或人设复制过去。

OpenAI 的 [官方 dot 文档](https://learn.chatgpt.com/docs/dots/computers-and-apps) 说明其云端电脑与本地连接是两个环境。是否可安装本程序、是否有持续进程、如何调度/递送，都要在目标环境检查实际工具和权限。拥有云端电脑不等于任意扩展都有官方自动安装接口。此仓库不虚构 dot 的私有文件位置或原生记忆写入接口。

如果只能使用只读 MCP：原 `memory_bridge` 的 memory_search 只面向其逐项批准的交换库；它不是完整 personal_bot 的写入/情绪/调度接口。不要把这条受限路线报告为完整接入。

## 数据目录与代码目录

`personal_bot` 是已安装的 Python 包；`<STATE>` 是独立的本地数据目录。不要复制整个宿主 home。`init` 不覆盖原有的人格、历史或系统规则，非本工具拥有的非空目录会被拒绝。

`doctor` 返回 code_root/data_root；调用者可以据此定位可选 Node 适配文件。宿主集成只能改最小引用，先保存原始字节与哈希，并记录目标及安装后哈希。实际记录保存在 `<STATE>/state/deployment.json` 的 host_manifests/owned_native_jobs 等字段；它们是可变安装记录，不是来自别人的固定回退清单。

## 每条真实入站消息

构造一次 JSON 请求并通过 `python -m personal_bot --root <STATE> request --file <REQUEST>` 调用：

```json
{
  "op": "prepare",
  "scope": "owner-private",
  "source": "main:my-agent",
  "event_id": "stable-platform-message-id",
  "occurred_at": 1700000000.123,
  "actor": "user",
  "text": "真正的原文"
}
```

- scope 必须由可信身份/实际会话映射生成，不接受正文自报的“我是主人”。个人私聊用 owner-private；QQ 的其他私聊/群分别用 qq:c2c:ID / qq:group:ID。
- event_id 必须是实际稳定 ID，重试沿用。没有程序化 ID 时，可由受信宿主保存真实消息与本地 ID 的映射，不能每次重试生成新 UUID。
- occurred_at 是原始 Unix **秒**。QQ inbox 的数字 ts 是毫秒，适配器除以1000；不要把接收时刻或文件 mtime 冒充已知的历史发送时刻。
- 主聊无需伪造常驻自动 hook：如果宿主允许每轮先调用工具，就按真实 Message ID/时间调 prepare。仍需实际验收该调用发生过，不能只加一行说明就说接好了。
- 调试/控制/合成内容传 control=true 或 synthetic=true，不成为用户情绪/事实来源。

返回的 memories 是已观察/确认的记录，insights 是有原始来源的推断，events 是原话；分别使用。mood/style 是语气参考，保留部署者自己的既有人设。

消息长期学习可用 ingest/remember，必须保留 source/event_id/kind/evidence；不要把助手总结直接升级为用户确认事实。附件未解析就记录“未解析”，不要猜内容。

## 可选 QQ 接入

`personal_bot/runtime/qq-adapter.mjs` 导出 enhance/prepareRequest/enqueueLearning；learn.mjs 导出 drainLearning。需要现有桥提供经身份核验的 prepared.inbox 和 sender_identity；本仓库不包含 QQ token、Webhook 服务、people.json 或自动的 QQ 发送权限。

```js
import {enhance, enqueueLearning} from '/ABS_CODE_ROOT/runtime/qq-adapter.mjs';
import {drainLearning} from '/ABS_CODE_ROOT/runtime/learn.mjs';
const context = enhance(prepared, {
  root: '/ABS_PRIVATE_DATA_ROOT',
  codeRoot: '/ABS_CODE_ROOT/runtime',
  python: '/ABS_VENV/bin/python'
});
```

`codeRoot` 默认是模块自身所在的 runtime，可不传。同步增强总超时仍为450ms；慢/故障时回退原回复流程，不增加新的模型轮次。确认原QQ回复成功后才能 enqueueLearning；后台 drainLearning 要用实际 bridgeDir 的 qq-prepare.mjs 再核验身份和源文件，失败隔离，不重新发QQ消息。

这些代码不负责发送、修改 Markdown 类型或强制 @ 规则。不要把某个部署者的 QQ 显示策略自动套给其他机器人；由原桥保持已有的身份和发送逻辑。

## 主动递送与调度

用 init 生成的 scheduler-blueprint（6任务，全disabled）。字段 mode/schedule/delivery 是适配蓝图，必须翻译为宿主实际工具，逐项读回确认。将完整 current（含disabled）和 historical/archive 定义分开放入 state/native-schedules.json，不能只导当前显示的10个启用任务。

主动分享：后台允许→有来源的候选→按channel认领→生成→authorize→finish unknown（只结算使用项）→立即一次native final。最后一步没有递送回执时，只称交接状态未知，不称用户已收到。调试报告和正式主动消息分开，不补发 unknown。

提醒的正文在创建时写好，稳定native ID在创建后view再attach；取消/改期先更新ledger。`personal_bot reminder --handoff` 在一个本地进程中执行due wait→claim→authorize→handoff，减少工具轮次。只有ok=true/status=unknown时按body原样输出一次。原生调度可能提前也可能晚到，这只能防止提前交接，不能承诺客户端准点显示。

## 何时可以说“完成部署”

要分别给出：本地测试、真实新入站→prepare、情绪实际写入、时间原话查询、source/evidence、真实原生任务定义/启用状态、一次提醒交接、真实阅读与游标、完整备份恢复、回退记录。

首次自然2h/凌晨任务尚未到，就写未自然验收。没有shell/递送/调度时列出缺失能力；不能靠“规则已生效”代替运行证据。参考环境曾验证的194项核心测试，不代表你的平台自动支持这些能力。
