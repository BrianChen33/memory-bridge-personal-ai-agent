# 抖音/B站的预留接口与实施路线

当前都为planned_not_enabled，不随贴吧插件激活。CONTRACT.json定义通用观察信封。
适配器提供canonical_source(input)、verify(native_receipt)、discover(cursor/budget)、
normalize_observation(packet,permitted_source)，共用许可、记忆、48情绪、语言习惯、分享与面板。

先做B站：主人指定UP主/合集/单视频链接，验证原生窗口能否取得标题/作者/时长、页面正式
字幕、实际画面或音轨。保存BV/AV ID、UP主UID、真实URL/时间轴/回执。评论/弹幕独立记录，
不冒充作者的话。推荐页需单独授权，不自动把发现的新作者加入许可库。

再做抖音：创作者/单视频/明确授权的推荐流分开。正常登录留在原生profile，一次少量视频，
达到时长/条数/精力预算就结束。先实测播放状态、字幕、可访问性，不照搬贴吧选择器。

证据类型必须分开：metadata_only、subtitles_read、frames_observed、audio_observed。
只有简介就说看到了介绍；有字幕只说明读了字幕；实际画面/音频记录观察时间段，不能用
封面/自动字幕冒充看完/听过。完整观看要求覆盖真实时长，跳看/预算中断标partial。
宿主拿不到画面/音轨时，明确降级为字幕/简介阅读；planner叙述仍须忠实归一化。

语言学习沿用机制候选→试用→稳定，不同视频/作者作为独立来源，同一视频循环不重复计分。
语调只能从真正听到的音轨学习；引文带时间轴，输出用她自己的语言。观点不自动写入SOUL。

实施时增加：真实provider注册、来源规范化/验证路由、observed_spans/subtitle_chunks的
覆盖校验、来源撤销与去重、一次最终隔离视频夹具验收和一个用户指定来源的真实能力验证。
使用已有生活/阅读任务，不复制heartbeat。不预装下载器/保存Cookie/建立伪观看任务。
