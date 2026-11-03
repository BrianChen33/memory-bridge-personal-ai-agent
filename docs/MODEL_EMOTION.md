# 模型情绪 v1：协议、接入与升级

v0.3 的情绪判断由宿主当前负责回复的模型完成；Python 核心只校验、去重和保存结构化结果。没有情绪关键词规则、额外情绪模型 API 或完整思考日志。整套生活/表情闭环见 [系统复刻说明](SYSTEM_REPLICATION.md)。

## 两阶段调用

先调用预读：

```json
{
  "op": "prepare", "scope": "owner-private", "source": "main:my-agent",
  "event_id": "stable-platform-message-id", "occurred_at": 1700000000.123,
  "actor": "user", "text": "把这一小块位置留给你"
}
```

通过 `python -m personal_bot --root <STATE> request --file <REQUEST>` 执行。返回原话/记忆/推断、当前衰减后的 mood/style；无评估时 `emotion.status=missing`，没有情绪副作用。`capture` 也只捕获，返回 pending_assessment。

宿主模型结合该结果、人设和近期对话判断 Agent 自己的反应，随后提交**同一个事件**：

```json
{
  "op": "prepare", "scope": "owner-private", "source": "main:my-agent",
  "event_id": "stable-platform-message-id", "occurred_at": 1700000000.123,
  "actor": "user", "text": "把这一小块位置留给你",
  "emotion_assessment": {
    "version": 1, "changed": true, "label": "害羞",
    "delta": {"p": 0.03, "a": 0.02, "d": 0},
    "intensity_delta": 0.04
  }
}
```

以上是合成示例，不能用于正式库或硬编码成所有对话的反应。第二次返回 event=replayed、emotion=updated 是正常的：原话先前已捕获，而有效情绪评估这次才提交。

使用返回的新 mood 组织回复、计算可选表情概率。普通聊天不展示内部 JSON/评分。`prepare.ok=true` 只代表请求完成，宿主还必须检查 `emotion.status`；不能把 missing/invalid 当作已完成评估。该包不强制控制宿主最终回复，before-reply 接入与最终提交校验由宿主实现。

## 协议与状态

- version 严格为非 bool 整数 1，changed 严格为 bool。
- label 为欣喜/难过/委屈/生气/害羞/期待/关切/专注/放松/失落/好奇/平静之一。
- delta 的 p/a/d 及 intensity_delta 必填；有限实数、非 bool，单次绝对值不超过 0.12。
- changed=true 至少一项增量非零。标签强度按有符号增量变化，没有固定 +0.1。
- changed=false 时 label=null、三个 PAD 增量与 intensity_delta 全为 0。只记 assessment_log，不写 mood/标签及其 at。
- PAD [-1,1]、半衰 6 小时；标签 [0,0.6]、半衰 45 分钟。先衰减再更新，纯读不写。

完整无变化信封：

```json
{"version":1,"changed":false,"label":null,"delta":{"p":0,"a":0,"d":0},"intensity_delta":0}
```

| emotion.status | 含义 |
|---|---|
| updated / unchanged | 有效评估已保存；可用返回状态回复 |
| replayed | 同事件同评估已存在，不再累计 |
| conflict | 同事件已有不同有效评估，保留首个，不覆盖 |
| missing / invalid | 尚无有效评估；修正后同事件重提仍可成功 |
| disabled_by_config | 本地可信总开关、mood 或 events/emotion_events 功能明确关闭 |
| ignored | 当前 actor 不可提交有变化评估 |
| error | 真实配置/状态错误，不能当显式关闭 |
| legacy_recorded | 升级前已更新过的历史事件，保留原结果且不重复应用 |

公开核心仅允许 user 事件引起变化。assistant/article/bot 不通过 changed=true；可记录它们的完整无变化评估。目标平台若需外来机器人来信或阅读材料改变情绪，必须实现额外可信来源路径与授权，不能仅信任任意 source 字符串。调试/合成事件不更新主人情绪。

旧 `mood` 底层 delta/label 写入接口为已有调用者保留兼容；**正常对话只使用 prepare + emotion_assessment**，mood 按只读使用。否则会绕过事件评估账本。不要把旧低层接口暴露成用户文本能直接操纵的命令。

## 宿主最小规则

> 在组文本轮回答前，读取真实输入、近期上下文、有界相关记忆和当前心情。结合人设与语境判断你对互动的反应；区分引用、玩笑、否定与实际对象，不复制用户情绪。不要求每轮变化，不为表情命中制造波动。提交结构化评估，校验成功后按返回的新 mood 自然回复；普通用户不看内部评估。缺失/非法需要修正，明确关闭时保留文字通道，配置损坏不能伪装为关闭。

稳定 ID/scope/actor 必须由可信适配器提供；同账号下的逻辑 scope 不是操作系统隔离。共享心情需用户授权和只读投影，不传 reason/私人原话，不允许外群改主人私有状态。公开包本次没有新增跨渠道共享或 QQ 发送实现。

## 从 v0.2 升级

1. 导出真实宿主任务和集成原件；完整 backup/verify。准备在隔离目录恢复，暂停相关入口时尽量缩短窗口。
2. 在独立环境安装 v0.3，先用新合成目录跑 self-test。不要直接覆盖线上人设或整份提示词。
3. 按两阶段流程更新主聊回复入口；更新主动任务规则，禁止根据任务时钟或自己的输出叠加情绪。
4. SQLite 初始化会用 CREATE TABLE IF NOT EXISTS 添加 assessment_log，不删除既有原话或 mood。旧情绪记录不回填成模型评估。
5. 旧事件已有 emotion_events 时返回 legacy_recorded，不能再次加情绪；只对真实新事件按 v1 验收。不要通过换 ID 把历史输入伪装成新来信。
6. 用真实新消息核对“输入→评估→持久化→新状态→回复”的顺序；再读回原生任务定义。默认不重注册一整套任务，不允许新旧两代同时发送。
7. 遇到不兼容，先本地 pause/rollback，再按保存的宿主原件恢复旧入口；保留新增数据与审计。`rollback` 不等于所有宿主动作已经完成。

测试入口：`python tools/test_all.py`、`python tools/check_wheel.py`。新增协议检查使用真实临时 SQLite，不调用 LLM；它们验证程序契约，模型理解能力仍需目标宿主真实对话验收。
