# 情绪与反馈 heartbeat · v0.8.3

本版保持六层。现有15分钟情绪任务同时承担反馈观测，不另建循环。重阅读/写作放原30分钟生活任务；提醒5分钟对账、2h阅读、每日维护/总结/备份保持各自职责。宿主繁忙时先照顾主人消息，有限工作可以下轮续做。

## 一轮任务顺序

1. 用真实后台许可检查；01–07允许静默状态/文件工作，不能主动发送。
2. companion_tick推进到期阶段；companion_activity pending检查是否需计划。简单计划可沿用本模型，但较长草稿/真实浏览交原生活任务，不在主聊生成。
3. companion_pending claim=true；使用返回emotion_template对每个原始事件填写full48，再companion_life_assess。invalid修同事件；别用旧信封。未准备的活动不宣称成果，不为每次tick固定加情绪。
4. 读正式主聊最近3–5turn，保留原生page/chat_id/turn.id/user原文/seq/occurred_at_ms。正常context/commit仅user；phase=audit仍只读。phase=feedback可保留必要真实assistant项供表达使用凭据，绝不当情绪刺激或复制cron交接。扫描最近24h并保留真实抽样覆盖；UTF-8请求最多60,000字节，跳过超预算的完整项并标partial，不截断原文。消息多时用宿主真实cursor分段，每轮最多2页/10turn，预算耗尽保存未覆盖的cursor，下轮续扫；页间遇已覆盖主人seq可结束情绪扫描，但实际输出学习须保留未覆盖进度。只读到定时任务交接不算已覆盖主人消息；不能宣称全量检查。
5. companion_feedback action=claim limit=2。对返回的每个真实原事件，结合其之前的3条来源、人设作回顾性评估（当前mood只是参考），填写full48；action=repair传source_event/lease/assessment。历史不足不猜：action=defer传source_event/lease/reason，标为needs_context留待核对，不冒充原始感受。最多3次失败，不无限重试。迟到增量按原始发生时间衰减，关系/期待/精力/旧输出不重放。成功的原事件永远跳过。
6. 主动分享只有值得分享时才做，既有quiet/dedup/claim/实际发送回执照旧。使用sticker_main phase=proactive而非用自己的输出prepare评估。生活传已评估的ct_life.source_event；新闻无新生活刺激传[]。每轮一次抽签，文字后图片。
7. 可抽查最多最近2份失败主动回执。只有精确原事件关联可证明时，companion_feedback action=receipt {round_id,output_event,source_events}记录更正依据。历史失败、抽签和送达记录保留，绝不通过重抽/补发“修复”。没有证据保持未知，不按相近时间猜。
8. 可选social-reading已装且启用时，实际输出由scan交observe_outputs；usage_work最多取3项，同一模型判断真实采用/语境后record_use。解释、引用与调试不计采用。personality_growth开启则habit_growth_work→同一模型反思→habit_growth_integrate；无证据/无变化可结束，不新增模型或定时任务，不给普通回复增加前置调用。详见VOICE_TRIALS.md。
9. 在finally等价路径运行面板heartbeat：即使某条修正失败，仍显示当前真实状态。相同原生run周期去重；失败保留上一HTML与实际时间，不能假装已更新。不向聊天发送面板完成通知。

```sh
python3 -m muse_ext.panel_refresh --root ACTUAL_STATE heartbeat --target EXACT_EXISTING_REGULAR_HTML --cycle REAL_EMOTION_RUN_ID --source-task ACTUAL_EMOTION_TASK_ID
```

先撤掉生活新闻任务原panel_refresh record/bind/runonce创建步骤，查询并取消确属旧系统面板的待发runonce。不能取消行程安排室、求职、邮件、提醒等其他页面任务。覆盖原资料库真实文件，不传入symlink，不另建一份页面。手动“更新系统面板”仍可立即publish --manual。

## 保留真实边界

SQLite ct_feedback/ct_feedback_scan/ct_feedback_receipt及ct_activity_*与原格式数据库一起备份；公开库不含私人原文。反馈检查不是平台发送拦截器。宿主没有native-final hook时如实说明。面板仍是每15分钟后台重建的离线快照，下载的旧副本不会自己更新。
