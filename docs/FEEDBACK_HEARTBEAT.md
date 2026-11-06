# 情绪与反馈 heartbeat · v0.8.2

本版保持六层。现有15分钟情绪任务同时承担反馈观测，不另建循环。重阅读/写作放原30分钟生活任务；提醒5分钟对账、2h阅读、每日维护/总结/备份保持各自职责。宿主繁忙时先照顾主人消息，有限工作可以下轮续做。

## 一轮任务顺序

1. 用真实后台许可检查；01–07允许静默状态/文件工作，不能主动发送。
2. companion_tick推进到期阶段；companion_activity pending检查是否需计划。简单计划可沿用本模型，但较长草稿/真实浏览交原生活任务，不在主聊生成。
3. companion_pending claim=true；使用返回emotion_template对每个原始事件填写full48，再companion_life_assess。invalid修同事件；别用旧信封。未准备的活动不宣称成果，不为每次tick固定加情绪。
4. 读正式主聊最近3–5turn，保留原生page/chat_id/turn.id/全部user项原文/seq/occurred_at_ms，移除非user正文；绝不复制整批助手或cron交接文字。phase=audit仍只读。phase=feedback单独扫描最近24h可修原事件，并保留真实抽样覆盖。消息多时用宿主真实cursor分段扫24h窗口，每轮最多2页/10turn，预算耗尽保存未覆盖的next_cursor，下轮续扫；页间遇已覆盖的主人seq可停止。只读到定时任务交接、不含user的页不算已覆盖主人消息；不能宣称检查了整段历史。
5. companion_feedback action=claim limit=2。对返回的每个真实原事件，结合其之前的3条来源、人设作回顾性评估（当前mood只是参考），填写full48；action=repair传source_event/lease/assessment。历史不足不猜：action=defer传source_event/lease/reason，标为needs_context留待核对，不冒充原始感受。最多3次失败，不无限重试。迟到增量按原始发生时间衰减，关系/期待/精力/旧输出不重放。成功的原事件永远跳过。
6. 主动分享只有值得分享时才做，既有quiet/dedup/claim/实际发送回执照旧。使用sticker_main phase=proactive而非用自己的输出prepare评估。生活传已评估的ct_life.source_event；新闻无新生活刺激传[]。每轮一次抽签，文字后图片。
7. 可抽查最多最近2份失败主动回执。只有精确原事件关联可证明时，companion_feedback action=receipt {round_id,output_event,source_events}记录更正依据。历史失败、抽签和送达记录保留，绝不通过重抽/补发“修复”。没有证据保持未知，不按相近时间猜。
8. 在finally等价路径运行面板heartbeat：即使某条修正失败，仍显示当前真实状态。相同原生run周期去重；失败保留上一HTML与实际时间，不能假装已更新。不向聊天发送面板完成通知。

```sh
python3 -m muse_ext.panel_refresh --root ACTUAL_STATE heartbeat --target EXACT_EXISTING_REGULAR_HTML --cycle REAL_EMOTION_RUN_ID --source-task ACTUAL_EMOTION_TASK_ID
```

先撤掉生活新闻任务原panel_refresh record/bind/runonce创建步骤，查询并取消确属旧系统面板的待发runonce。不能取消行程安排室、求职、邮件、提醒等其他页面任务。覆盖原资料库真实文件，不传入symlink，不另建一份页面。手动“更新系统面板”仍可立即publish --manual。

## 保留真实边界

SQLite ct_feedback/ct_feedback_scan/ct_feedback_receipt及ct_activity_*与原格式数据库一起备份；公开库不含私人原文。反馈检查不是平台发送拦截器。宿主没有native-final hook时如实说明。面板仍是每15分钟后台重建的离线快照，下载的旧副本不会自己更新。
