# JSON API 与验收

命令入口：`python -m personal_bot --root <STATE> request --file request.json`；也可在stdin传UTF-8 JSON。单次不超过65536字节，正文最多12000字符。读取结果中的ok及具体reason：澄清/静默/未到点是结构化结果，不一定是程序崩溃。CLI在ok=false时返回非零，但保留JSON字段。

运行时由 standalone core 处理，文档操作名来自实际dispatch，不是额外的远程API。下面值都是示例，不要把合成数据写入正式个人库。

## 常用操作

| op | 关键字段 | 含义 |
|---|---|---|
| prepare | scope/text/source/event_id/occurred_at/actor | 原话捕获 + 来源情绪更新 + 检索 + 语气参考 |
| capture | 同上，actor=user/assistant/bot/article | 仅记录真实事件及适用的情绪观察；不能充当递送回执 |
| remember / ingest | scope/text/source/event_id/kind/evidence | 存储带出处的记忆/附件解析证据 |
| recall | scope/text，可选start/end | 中文时间解析或显式半开数字范围；返回原话/记忆/有来源推断 |
| correct / forget | scope/id，correct另带text/source/event_id | 纠正/遗忘并阻止关联旧内容复活 |
| mood | scope | 读取衰减后的PAD与标签；正常更新走prepare，不重复累加 |
| derive | scope/sources/text/kind | reflection/skill/lesson，明确inference且来源仍有效 |
| consolidate | scope/action=propose/merge/undo | 源哈希复查、等价合并视图、冲突、撤销 |
| vector_index | scope/limit<=20 | 本机有界后台索引；模型不可用就失败/保留关键词 |
| reading | scope=owner-private/action=claim/commit/status | 白名单文档阅读、租约、原文与推断笔记、游标 |
| reminder | scope=owner-private/action | 提醒生命周期，见下 |
| proactive_check | scope=owner-private | 实际系统时钟下background_allowed/can_notify |
| life / news | scope=owner-private及实际sources/评分字段 | 生成待分享候选；news还验证当前画像/日期/阈值 |
| digest_claim / digest_authorize / digest_finish | scope/channels/lease/epoch/expressed_ids | 跨入口共享认领/去重和最终来源复查 |
| maintain | scope | 归档超期低重要性的episode |

`source` 是溯源记录，不是密码学认证；身份和操作授权必须来自宿主的可信适配器。作用域是逻辑隔离，拥有本地执行权限的同一代理仍能读本地文件，不是多租户安全边界。

## 时间与情绪

同一真实消息重试沿用source/event_id/actor；内容变更会拒绝。同一事件不重复更新PAD。数值有限幅，PAD六小时半衰、标签45分钟半衰；这些表示语气推断。纯读取不会凭时钟产生新情绪事实。

`recall {text:"昨天早上我说了什么"}` 按北京时间5–12点取昨天user原话；`{start:...,end:...}`优先使用明确范围。insights按笔记自身occurred_at过滤，并保留原始来源ID，不把推断当用户原话。没有记录就回答没有源记录。

## 提醒闭环

1. `reminder/create`：text为原始时间请求，body为预先写好的正文，source/event_id为实际请求来源；如“明天三点”不明确上下午，返回needs_clarification，不能猜。
2. ledger返回id/version/native_job_id/native_at/timezone。宿主先查同ID原生runonce，再创建或复用、view核对后`reminder/attach`。
3. runonce执行：`python -m personal_bot --root <STATE> reminder --id ID --version N --handoff`。最多等待900秒，实际到点后复查配置、版本、取消、epoch、静默与租约；提前唤醒不提前发。
4. 仅ok=true/status=unknown时，立即把返回body原样作为一次native final。unknown是已准备交接，不是客户端回执；不能自动重试。
5. `cancel`先围栏，再停返回的native job并`ack_disabled`。`reschedule`提升version、停退休ID、创建新version的稳定ID再attach。
6. `pending`给恢复任务对账，不能用5m对账代替runonce计时。life模块暂停不应取消用户明确请求的提醒；总开关/提醒功能关闭会阻止交接。

默认夜间延期到07:00；只有用户明确指定夜间提醒时，创建请求才传quiet_override=true、quiet_permission=explicit_user_request。不要从检索文字推断这项权限。

## 阅读闭环

在`<STATE>/library/`缓存已授权的公开UTF-8文本/Markdown；登记reading-sources.json：

```json
{"version":1,"documents":[{"id":"sqlite-backup","path":"library/sqlite-backup.txt","source_url":"https://www.sqlite.org/backup.html","public":true}]}
```

`reading/claim`返回精确text/source_hash/start/end/lease；宿主实际阅读后用chunk_id/lease/summary调用commit。代码再次核对源文件、原子写episode/observed原文和reflection/inference笔记，才前进cursor。失败不前进，重复提交不重复写，源已变更需重新认领。

笔记可以`life {sources:[quote_id],topic:"reading:文档:哈希:位置",text:有价值观察}`入队，经reading channel正常gate后分享。新闻不能冒充阅读绕过画像/阈值。

## 等价合并

propose只给候选。merge必须提供同scope、兼容kind/evidence的ids、每源当前fingerprint的hashes、精确quotes、relation=equivalent或contradiction、明确reason。数字/日期或否定变化保留为conflict，原文不覆写。undo只撤视图，不复活已forgotten/superseded的源。

## 分享约束

digest_claim的channels可取life/news/emotion/reading；不同任务只处理自己的channel。取得lease/epoch后依来源生成，再authorize并finish unknown。expressed_ids只填本次实际表达的ID，未用候选留待后续。任一最终来源失效、画像/阈值改变或跨静默边界时，按返回拒绝；不要自行补发。

完整备份使用`personal_bot backup`，不要将底层旧的op=backup（仅SQLite）当完整备份。
