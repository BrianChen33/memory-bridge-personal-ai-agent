# 连续虚拟活动与作品

普通生活活动保存为一个有具体主题、阶段和作品的项目。选择“写小故事”只是开始；
同一个宿主回复模型还需要准备写什么、怎样展开，以及完整原稿。程序只验证、计时、
保存和按阶段开放内容，不替模型编造过程或知识。

这是虚拟日常。真实刷手机继续使用 [LIFE_ROUTINE.md](LIFE_ROUTINE.md) 的同一
`phone_intent` 与实际观察；手机、真实阅读和梦境不进入项目计划。虚拟“阅读/学习”
也不能据此声称访问过外网、读过某个真实页面或掌握了未经核实的资料。

## 复用现有任务

15分钟情绪任务运行 `companion_tick`，推进已经准备好的阶段，再处理待评估事件，
完成既有反馈检查和静默面板刷新。30分钟生活/新闻任务承担较重的主题选择和原稿准备：
在原有生活工作中读取 `companion_activity pending`，由本次运行的同一宿主模型提交
`plan`，或在暂停后提交 `revise`。不另建项目定时器，也不为每分钟、每次普通聊天
调用另一个模型。保留原来的阅读、提醒、维护、备份节奏。

新活动的 `project_id` 同时是其 `ct_life` 开始事件ID。旧的普通活动第一次被新运行时
接管时，从本次访问重新开始规划，不倒填之前没有记录的经历。没有计划时保持
`awaiting_plan`；原先预估的结束时间过去，也不会产生“已经学会/已经写完”的结果。

所有入口限可信宿主的 `owner-private` scope，并服从生活功能开关。scope 字符串本身
不构成身份认证。群聊不获得主人项目上下文。

## 获取待规划项目并提交

```json
{"op":"companion_activity","scope":"owner-private","action":"pending"}
```

`projects` 只列当前 `awaiting_plan` 或 `paused` 项目，返回真实 `project_id`、活动名、
当前 `version` 和已开放阶段；没有待办时为空列表。响应也返回字段名、阶段数和时间
边界。不要把空列表当成需要自行制造另一个项目。

下面是两个阶段的完整请求。把 `PROJECT_ID` 替换为待办中返回的真实值；`activity`
必须逐字等于该项目的活动名，本例要求待办活动是“写小故事”。实际主题、阶段和原稿
由当前模型依照本人人格及当前状态撰写，不照搬示例。

```json
{
  "op": "companion_activity",
  "scope": "owner-private",
  "action": "plan",
  "project_id": "PROJECT_ID",
  "expected_version": 0,
  "plan": {
    "version": 1,
    "origin": "virtual",
    "activity": "写小故事",
    "topic": "给月亮修理钟表的猫",
    "stages": [
      {"after_seconds": 300, "description": "写好开头：修钟猫推开月亮钟表店的门，却发现店里所有的钟都没有指针。"},
      {"after_seconds": 600, "description": "写完并修改了结尾：猫剪下坏钟的影子做成指针，钟声终于重新响起。"}
    ],
    "artifact": {
      "title": "月亮钟表店",
      "text": "修钟猫推开月亮钟表店的门。店里所有的钟都没有指针。\n它找了很久，最后剪下坏钟的影子，裁成两根细细的指针。\n第一声钟响时，月亮轻轻晃了一下。"
    }
  }
}
```

`plan.version=1` 是计划格式版本；请求的 `expected_version` 是项目当前版本，首次为0，
保存后递增为1。二者用途不同。计划字段必须完整且无额外字段：

| 内容 | 限制 |
|---|---|
| `origin` / `activity` | 必须为 `virtual` / 项目原活动名 |
| `topic` | 非空，最多160字符 |
| `stages` | 2–6项，每项仅 `after_seconds`、`description` |
| `after_seconds` | 有限数，1–21600秒，严格递增，不接受布尔值 |
| 阶段描述 | 非空，每项最多1800字符 |
| `artifact` | 仅 `title`、`text`；分别最多160、24000字符，均非空 |

阶段偏移以**本次计划被接受的时间**为起点，末阶段确定新的结束时间，并同步当前
活动时间。迟到的计划从现在开始，不会因为旧活动开始得早而瞬间“完成”一篇原稿。
相同 `expected_version` 和相同计划的重试返回 `replayed=true`；改写同一已接受版本
会报内容冲突，旧请求不能覆盖后续版本。

## 普通查询和显式取作品

```json
{"op":"companion_activity","scope":"owner-private","action":"view"}
```

省略 `project_id` 时查看当前活动；提供真实 `project_id` 可查看已知项目。普通
`prepare` / `companion_context` 自动使用同一种精简投影：状态、主题、时间，以及最近
最多三个已经到达的阶段，正文总量约1200字符以内。`visible_count` 表示已开放总数，
投影文字可能截短；SQLite里的阶段原文保持完整。未来阶段、完整计划和作品原稿不会
进入普通上下文、回忆、待评估列表或面板。

阶段到点后即可在只读查询中看见。对应的正式生活/来源事件由现有任务的下一次
`companion_tick` 登记；完成状态以正式登记为准。不能根据预估结束时间自行宣称一个
没有计划的项目已经完成。

需要作品时显式请求，并且必须指定项目：

```json
{"op":"companion_activity","scope":"owner-private","action":"artifact","project_id":"PROJECT_ID"}
```

此入口会先登记该项目已到点的阶段。全部阶段正式完成后，才返回 `ready=true` 与
原格式的 `artifact.title/text`；提前请求只返回 `ready=false` 和安全投影。原稿在
准备时已保存，不在取稿时临时重编。已经完成的项目即使不再是当前活动，也能按ID
重复取稿；取稿本身不重放旧回复、不重新抽表情，也不把自己的作品作为外部情绪刺激。

## 暂停与只修改未来

```json
{"op":"companion_activity","scope":"owner-private","action":"interrupt","project_id":"PROJECT_ID","expected_version":1,"reason":"先停下来接一句话"}
```

暂停前先登记截至此刻已到点的阶段；这些已发生的原文、来源和时间不再修改。暂停
期间未来阶段即使超过原定时间也不会开放。未规划项目也能以 `expected_version=0`
暂停，恢复时提交初次 `plan`，从新的接受时间开始。

已有计划的项目暂停后，将请求改为 `action:"revise"`，提供其当前 `expected_version`
和同样结构的完整 `plan`。其中 `stages` **仅描述未来**的2–6个新阶段，偏移重新从
本次接受时间开始；模型要结合已开放经历续写作品。旧的未开放阶段作废封存，已经
开放的阶段继续保留，不把“重写未来”当成改写过去。程序保留旧原稿，当前作品取稿
只使用最新接受版本。完成后的项目不能暂停或修订。

项目写入、推进、暂停、修订和取稿共用一个进程锁，避免来源事件独立提交时被另一个
进程穿插改稿。繁忙时返回 `activity_project_busy`，让既有工作稍后重试；不强删锁、
不创建新任务。锁文件只用于互斥，活动正文均在SQLite内。

## 阶段情绪与备份

每个到点阶段仅登记一次正式 `ct_life` / `source_events` 事件，`origin=virtual`：
中间阶段为 `progress`，末阶段为 `completed`，开始记录仍保持 `started`。稳定事件ID
同时覆盖重试和“来源已提交、阶段回执尚未保存”的恢复情形。生活相机的已有完成绑定
继续使用末阶段的正式完成记录，不能靠等待时间触发一张未完成成果照。

情绪任务通过 `companion_pending {claim:true}` 获取这些正式事件，使用返回的当前
`emotion_template` / `emotion_frame` 由同一宿主模型填写 full48，再调用
`companion_life_assess {id,assessment}`。后续分享仍走既有 claim、实际发送和回执流程，
遵守安静时段。隐藏的阶段和未开放原稿不能提前用于评估；已经成功的事件不能重复加
情绪。不要把未来阶段的草稿当成模型已经经历过的刺激。

项目状态、每版完整原稿与阶段回执分别保存在 `ct_activity_project`、`ct_activity_plan`、
`ct_activity_stage`。原格式SQLite私库快照自动保留这些表，不导出几十份作品散文件，
也不把私人主题、原稿或数据库放入公开代码仓库。继承时恢复原SQLite及匹配的运行时
版本，原生任务仍须按真实宿主接线与读回；文件存在不等于任务已运行。
