# 响应式小屋面板

`companion_panel` 继续生成单文件只读 HTML。横屏卡片总览，手机双列卡片与全屏详情；48种情绪按当前强度降序，支持分类/搜索。未记录不等于0；精力、关系、生活、实际开关和生成时间读取现有记录。页面不调用模型，不新增情绪事件，不参与聊天表情抽签。

## 私人人格和可选素材

通用模板不捆绑作者的人格、实际记忆或任何第三方GIF。部署者在私有STATE保存 `panel-profile.json`，可包含 `title/short_name/nickname/tagline/greeting/presence/room_hint` 和 `voice`（happy/curious/relaxed/sad/angry/tired/affection/reading的简短展示文案）。页面文案是界面呈现，不能回流为已发生的生活或聊天。

可选图片放在 `STATE/assets/panel/`；`manifest.json` 为：

```json
{"attribution":{"author":"实际作者","site":"实际来源"},"items":{"happy":{"file":"happy.gif","sha256":"完整SHA256","caption":"简短说明","source":"原始公开来源"}}}
```

固定8个可选键与voice一致。只读目录内GIF/PNG/WebP，单张最多3MB、合计12MB；检查路径和可选SHA，内嵌data URI。无素材时使用通用图标，配置损坏则生成失败，保留原有效资料库文件。使用大肥鱼等第三方素材应遵守其许可并保留作者链接；公共代码仓库不再分发素材。

### 避免把原始动图全部塞进大文件（v0.6.2）

Base64比原图约大三分之一，8张原GIF可能让HTML超过10MB。可在部署时对**独立面板目录**转换一次：

```sh
python tools/compact_panel_art.py --root STATE
```

该工具需已有ffmpeg，默认160px、8fps、质量55的循环动画WebP；保留8类表情、来源、署名和单文件离线功能，原聊天图库不变。转换后原子更新私人manifest的文件名、SHA及编码参数；同参数重跑不再次有损编码。按面板实际显示尺寸调整参数，发布后读回真实HTML字节数，建议控制在1MB左右。运行时只读成品，半小时刷新不重复转码，也不需要ffmpeg。确认新manifest与页面可用后，可清理面板目录内不再引用的旧副本，不能清理聊天原图库。

私库保存更新后的manifest及原始source/source_hash/source_sha256；在新环境从原始公开素材重建，再执行同一转换即可。压缩素材仍留私人环境，不上传公共代码仓库。

表情概率从实际 `expression-policy.json` 读；采用宿主自己的表情配置时，每次刷新可把该配置的 `enabled/base_probability/maximum_probability` 只读投影到 `state/panel-sticker-policy.json`。它是展示快照，绝不回写或代替原策略。

## v0.8.2 当前规则：情绪heartbeat末尾，每15分钟

新接线使用既有15m情绪任务的最后一步；不再等待5分钟、不再由30m生活新闻任务创建面板runonce。
调用前先完成本轮状态推进/有限反馈检查；有单条失败也显示实际失败状态，不假称全成功。

```sh
python3 -m muse_ext.panel_refresh --root STATE heartbeat --target EXACT_PRIVATE_LIBRARY_HTML --cycle REAL_EMOTION_RUN_ID --source-task ACTUAL_EMOTION_TASK_ID
```

迁移时：删掉原生活新闻任务中的record/bind/创建runonce步骤；查询并取消**确属旧系统面板**的待发
panel-refresh任务。不要取消行程安排室、校招、邮件、提醒或其他页面刷新。读回原任务ID/body/时区，
保持原资料库HTML真实目标和符号链接。heartbeat模式会拒绝旧record/bind，旧周期publish返回stale。
同一真实运行周期去重，下一次预计时间为15分钟后；原生调度延迟如实显示。手动更新可立即publish --manual。
面板保持单文件、离线、静默覆盖；已打开的预览可能要刷新或重开，下载的旧副本不会自行变化。

## 旧版机制的退役

旧版从30m事件结束时间推迟300秒，再动态创建runonce。该规则已取消；兼容函数仅供旧版本状态读取，不能用于新部署。启用heartbeat模式后旧record/bind拒绝重新排程，旧cycle的publish不会覆盖当前页面。

## 安装与继承

安装新模板、`panel_home.py`、`panel_refresh.py`，在原 `panel()` 生成snapshot后调用 `panel_home.enrich(b,snapshot)`。保留宿主的备份/路径定制，不整文件覆盖定制版companion_io。包和wheel应包括同一模板。

私库原格式备份登记小型 `panel-profile.json`、素材manifest、面板任务状态与只读策略投影；可从公开源重建的GIF无需每日复制。真实素材和私人文案只留私人环境。新Agent继承后先核对原生任务，再启用，不复活历史runonce。架构commit、版本与公开维护说明照常同步。
# v0.7 optional-plugin card

The eighth overview card is now 阅读与成长, replacing the panel-update card.
It shows explicit plugin installation, source verification, actual partial reading
and evolving speech habits. Core-only installs show 未安装; empty allowlists show
待配置. Future Bilibili/Douyin are planned, not active. Refresh timing and binding
details remain accessible through About; refresh now runs at the end of the existing 15-minute emotion heartbeat.

## v0.8.6 口头禅小册

阅读与成长中的词条改成关键词标签，按试用中、已用熟、仅理解、待理解、已停用分组；
未知状态归入待整理。显示当前快照中实际提供的词条数量，不冒充数据库的全量统计。
支持本地关键词搜索、状态筛选、每页24项；列表有高度上限，横竖屏均换行。
释义、例句、场景、来源和使用流水不再渲染，也不藏在悬浮提示里。学习数据和规则未改。

这是模板展示更新，无额外模型、网络请求、任务或数据迁移。只替换companion_panel.html，
保留私有素材与路径定制，按既有heartbeat入口静默生成同一资料库HTML。
