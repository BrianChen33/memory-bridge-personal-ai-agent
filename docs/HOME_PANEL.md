# 响应式小屋面板（v0.6.1）

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

## 每半小时，事件完成后5分钟

不另造一套心情判断。复用已有30分钟事件任务，在真实状态更新成功后执行：

```sh
python -m muse_ext.panel_refresh --root STATE record --cycle REAL_HOST_RUN_ID --source-task REAL_HOST_TASK_ID
```

它固定首次完成时间、`due_at=ceil(completed_at+300)`、确定性`task_name`和Asia/Shanghai的`at_local`；相同周期重试不推迟。宿主查询同名任务去重，以正式原生工具创建一次性静默任务。只支持agent任务的宿主也应让该任务只执行下述本地命令，不能重新聊天、阅读、判断情绪或总结。

恢复漏掉的真实周期时，可用 `record --completed-at UNIX_SECONDS` 传入正式工具读回的实际成功结束时间，不能用当前时间伪造过去的完成时间。已过due的runonce按宿主真实catch-up语义处理，只补最近周期，不重放整段历史。

```sh
python -m muse_ext.panel_refresh --root STATE publish --target EXACT_PRIVATE_LIBRARY_HTML --cycle SAME_REAL_HOST_RUN_ID
```

创建并读回实际任务ID/时间/enabled/delivery=[]后执行 `bind --cycle SAME_REAL_HOST_RUN_ID --task-id ACTUAL_NATIVE_TASK_ID`。若创建后在绑定前中断，重试先查确定性名称，不重建。runonce的时间格式和时区以宿主真实schema为准；不能把本项目的Unix秒直接当作每个平台的时间参数。

发布命令使用真实时钟，提前运行返回waiting且不写文件；过期周期跳过，已发布周期不重复。独立文件锁不占用情绪/聊天数据库写锁。先完整生成再原子替换指定HTML，不碰聊天通道；错误保留旧版。定时任务的原生唤醒可能有少量延迟，记录实际生成时间，不假称准秒执行。`next_at`是下一周期预计时间时带`next_estimated=true`。

初次安装或用户明确要求手动刷新可执行 `publish --target EXACT_PRIVATE_LIBRARY_HTML --manual`，如实记录manual。不能伪造一次成功生活事件来触发安装验收。暂停/取消自动更新，应停用原生待运行任务并撤掉源任务末尾步骤，再记录enabled=false。

Muse资料库适配示例：覆盖宿主已经使用的 `workspace/your_files/Muse系统面板.html`；保留宿主实际文件名和路径。Library预览缓存行为必须实际点开核验，下载到别处的旧HTML不会变成实时网页。页面没有后台网络API。

## 安装与继承

安装新模板、`panel_home.py`、`panel_refresh.py`，在原 `panel()` 生成snapshot后调用 `panel_home.enrich(b,snapshot)`。保留宿主的备份/路径定制，不整文件覆盖定制版companion_io。包和wheel应包括同一模板。

私库原格式备份登记小型 `panel-profile.json`、素材manifest、面板任务状态与只读策略投影；可从公开源重建的GIF无需每日复制。真实素材和私人文案只留私人环境。新Agent继承后先核对原生任务，再启用，不复活历史runonce。架构commit、版本与公开维护说明照常同步。
# v0.7 optional-plugin card

The eighth overview card is now 阅读与成长, replacing the panel-update card.
It shows explicit plugin installation, source verification, actual partial reading
and evolving speech habits. Core-only installs show 未安装; empty allowlists show
待配置. Future Bilibili/Douyin are planned, not active. Refresh timing and binding
details remain accessible through About; the existing silent refresh job is retained.
