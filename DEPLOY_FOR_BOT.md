# 给部署 Agent 的执行手册（v0.8）

先读README里的完整提示词。它规定顺序：能力摸底→人格与选择→核心→真实宿主接线→专用任务→面板/可选私库→一次最终隔离验收。不要只写几条规则就宣布完成。

## 1. 能力与人格

查询真实环境的持久磁盘、Python3.10+/SQLite FTS5、可信身份/消息ID/Unix秒时间、原生定时/一次性任务、主动消息和图片工具schema。保留原机器人正在使用的身份与业务通路。没有的工具标未支持，不造参数。

按照docs/PERSONA_ONBOARDING.md补齐人格；已有充分人设不要覆盖。QQ、微信、表情、私有GitHub备份分别询问缺失选择，默认关闭。本人确认过的选择无需重复问。

## 2. 安装与核心

```sh
git clone https://github.com/BrianChen33/personal-ai-companion-kit.git
cd personal-ai-companion-kit
python -m venv .venv
# 激活当前系统对应的虚拟环境，再执行：
python -m pip install .
python -m personal_bot --root "<STATE>" init
python -m personal_bot --root "<STATE>" enable
```

STATE必须在源码checkout外。init默认保留已有配置，拒绝覆写非本工具拥有的非空目录。新root设置companion_v2=true；旧v0.3 root保持原行为，明确升级时执行`companion-upgrade`。核心模型、记忆数据、平台权限互相独立。

## 3. 绑定每轮真实消息

1. 可信适配器派生scope/source/event_id/occurred_at/actor/person_id；不要信正文自报身份。主人私聊、其他私聊、各群分开。
2. `prepare`预读原话、memories/insights/events、mood、companion、scene_context/persona_context。
3. 当前回复模型读取companion_schema的48词表，按真实入口返回的模板填写；新reply_driver用compact48-v1只报实际变化、未报为0，旧full48-v1仍须全键。结合人格/需要/精力/责任/期待判断，配合不自动变开心。同一源事件再次prepare写入并读回mood与本轮reaction，检查updated/unchanged/replayed及主聊pipeline_ok；invalid读取emotion_validation.detail修正同一源，不重新抽签。具体字段、幅度与六类摘要见MODEL_EMOTION.md；不能把missing/invalid或降级抽签当作评估成功。
4. 按新状态组文；若启用表情，调用expression策略并按宿主真实媒体接口发送，先全部文字后图片。自己的最终输出只可记原话，不产生自循环情绪。
5. 能提供正式hook就使用hook；只能靠prompt约定时如实标注。任何channel数据不得写入其他人的私有scope。

6. 按docs/HUMOR.md转交expression_context/emotion_effect；原回复模型可在已有prepare里带humor_assessment/meme_updates。主人一句话改串子/情绪倍率时认证身份，调用companion_expression_config、核对revision再生成面板；群友只能停止对自己的定向调侃。默认主动串关、程度50、独立反击开、倍率1.0。不要把倍率再乘进模型的原始情绪增量。

7. 梗库可选seed，普通聊天只读本地。原生任务按蓝图每周日07:40同步一次公开API，不默认建立每日任务；静默并保存partial进度，不注册投稿凭证、不向Wiki上传聊天。公共更新与私人语境学习分开，所有认知表都在原格式SQLite内。

纯@必须由可信QQ归一化层保留mention元数据、metadata_only=true/content_type=mention_only；保持原始空正文。无负载垃圾空白应在入口忽略；有媒体空正文需单独的媒体适配，不能伪造用户原话。

## 4. 人物、后台任务与来源

先显式绑定people_json/people_dir与person_map。统一稳定ID，允许同名未确认记录暂时分开；角色/管理员权限从可信身份配置获得，不由好感度决定。

按docs/HOST_TASKS.md将蓝图改成实际平台任务并读回。生活tick只产生带标签的虚拟/梦境事件，再由模型评估；真实阅读通过capture+companion_observe进入待评估列表。每个scope的摘要后台生成，有来源才可提交；错误/删除原文时旧摘要不再注入。

## 5. 可选渠道与数据迁移

QQ/微信没有跨平台通用安装命令。询问是否启用后读取目标官方文档/宿主工具，核对鉴权、回调、入站ID、回复窗口、主动消息限制和媒体接口。凭据写到宿主正式秘密存储，不写GitHub。

原有机器人@规则保留；参考配置可选择人类群回复不@、机器人只首句真@，不能强加给其他部署者。网络超时应有限，单条无效消息不阻塞队列。

继承按docs/INHERITANCE.md。复制到新的隔离数据目录，宿主任务默认停用；不得将旧运行时路径、native定义或已发送提醒当可直接激活的指令。

## 6. 面板与GitHub

网页、资料库 HTML 与空间统一读取 docs/WEB_SPACES.md。先定位真实页面类型、源码或生成器、数据与发布入口，再更新原页面。采用一个主要任务、简洁概览与按需详情，删去标语、教学式提示和次要标签，以语义控件同时服务用户、开发者与智能体。核对功能、数据和访问范围，并做一次桌面及375px验收。

可选“阅读与成长”插件：用户选择后按plugins/social-reading/README.md单独安装/启用，
安装后由机器人在主聊用本人人设问主人许可的贴吧；别让安装者提前代填。读取PROTOCOL.md，
接入真实原生浏览器与既有阅读/生活任务。来源未配置/未验证就暂停自动读；不复制DSH驱动。
将plugin_context及expression_context.learned_voice实际交给回复模型。新增sr_认知表和plugins.json
随私库继承；插件代码按锁定commit重建，旧登录态/任务不自动恢复。面板第8卡改为插件，
静默刷新改为现有15m情绪heartbeat末尾，撤掉旧30m+5m及其待发runonce，状态详见“关于”。B站/抖音的disabled接口不是已完成部署。
人格成长单独征得主人选择，已明确同意无需重问。开启后同一阅读模型reflect带growth_candidates，
每轮current_persona.growth_overlay与SOUL共同构成当前人格，允许改变可变性格，不能仅当措辞。
参阅docs/PERSONALITY_GROWTH.md及docs/LIFE_ROUTINE.md，默认40%日常/60%手机，所有自动
社交阅读入口消费同一life_intent，保留原生任务节奏，不另建刷帖循环。

v0.8.2接线必须再读LIFE_PROJECTS.md、MAIN_ENTRY.md和FEEDBACK_HEARTBEAT.md：具体活动由同一模型
后台准备，普通回复只读当前阶段；commit复用上下文而不再prepare；主动输出不重复评估自己。
反馈只对真实近期缺失/无效原事件做按原时间衰减的有限修正，已成功、关系、期待、抽签和旧发送不重放。
每日原格式SQLite快照已包含ct_activity_*和ct_feedback_*，不拆成大量单独作品文件。

v0.8.3/plugin0.3.0必须再读docs/VOICE_TRIALS.md。每次真实阅读优先lexical_candidates最多8项，
另style_candidates最多3项；同一模型理解即trial，不再等3帖。旧候选从实际归档逐项review/拆词，
不批量改trial、不伪造采用次数。主人词义/场景/语气纠正分别更新，明确stop不得自动复活。
在现有15m反馈任务的phase=feedback保留必要真实assistant项，按60KB总预算只传完整原文；
usage_work→同一模型判断实际合适采用→record_use；3次跨2轮后稳定，不依赖主人表扬。
已获人格成长授权时habit_growth_work→同一模型反思→habit_growth_integrate，真正投影到当前
persona_growth.traits，而非只写面板或按词频改性格。原任务末尾照常静默刷新同一面板。
普通context/commit仍仅取user，普通回复不新增前置调用。升级保留真实许可、阈值和其他设置。
原格式SQLite已含sr_habit_profile/sr_output/sr_usage/sr_habit_growth*，私库架构锁更新到实际版本。

`companion_panel`输出`exports/Companion面板.html`。按实际资料库文档发布；没有API/刷新证据就保留离线方式。GitHub只在用户选择后配置，使用专用私库；`vault.py`保留原始SQLite、按SHA去重原生文件、锁定架构commit。

## 7. 一次最终隔离验收与报告

组装完再跑一次，临时数据库与mock发送，清理本次夹具；必要修正只聚焦失败点，不循环扩大测试。可以把回归与wheel安装合并成这一次验收。部署不强制真人测试；真实消息仅在本人明确授权后进行。

最后读回配置、任务启用状态、实际安装文件/代码版本、备份远端commit和面板文件。分别标记本地通过、宿主已接通、送达已证实、自然触发未观察。缺口明确写出。保持人格回应普通用户；调试通道按用户要求独立。

架构维护：每次架构/协议/代码/部署说明更新，按docs/MAINTENANCE.md同步公开GitHub与私库架构commit锁。远端SHA未确认不能称同步完成。清理旧情绪指令，历史个人经历保留。

## v0.8.1 正式入口收敛

先读docs/MAIN_ENTRY.md。Muse真实工具返回按main_native_entry.mjs的严格形状取源；其他宿主
按自己的schema适配。当前模型context后填full48，再commit；ready_to_send=false修同源，
不把脚本检查说成平台拦截。长浏览返回重读新来信，真实读帖用finalize_reading+completion。
既有情绪任务做只读抽样audit，不另起定时器，不回放历史情绪或重发旧消息。

正常context/commit允许无损用户项投影：保留真实chat_id/page/turn.id及每turn全部user的原文/role/seq/时间，移除助手项；不复制无关长回复，不改写或截断用户正文。phase=feedback按v0.8.3额外保留必要真实assistant项，仅供表达使用证明。

## 当前v0.9.0 / runtime2.7.1 / social-reading0.4.0
按docs/FAST_REPLY.md装固定reply_driver+reply_media与依赖，安装时读协议一次。每轮真实取源→
context票据→同模型compact48实际变化→commit扩展完整48项，一次抽签并本地选图，原生final先短句后图。
不能先回正文后补评估；不重复prepare、临时写builder或为多个短句重抽。没有真实回执不先finish。
更新现有emotion/life-news/reading正文并实际读回：15m只短检查/入队/情绪/反馈/面板，禁止浏览；
30m与2h统一queue_work最多一批，预算从实时配置读。全部手动/手机入口按READING_QUEUE.md，
停用旧直接plan和过期重plan惯例。若手动需要近期启动，用queue_handoff未来计划及实际任务读回。
先核对已有浏览的真实状态，不直接抹掉租约；不改变任务身份、主人配置、成长记录或渠道发送器。
同一面板静默覆盖；最终私库snapshot/README/LATEST/manifest都锁定实际发布commit。

## v0.8.5部署差异
固定新版SHA部署emotion_full48.py、companion.py、main_commit.py、sticker_main.mjs、reply_driver.mjs，
配套当前MODEL_EMOTION/MAIN_ENTRY/FAST_REPLY。插件0.4.0不重装。词表/历史/默认配置/表情
概率不变；新driver精简输入，旧频道/生活/反馈模板保持兼容。私有SOUL/入口只精准替换与
现策略冲突的情绪操作句，不加长整套规则、不覆盖外形与人格、不加新定时器或前置模型。
做一次隔离同模型配对校准，不向主聊/生产队列发送假消息，不能把“模型口头同意”当验收。
核实际评估与简短表达、完整48保存和幂等。发布后同页面板及私库锁同步到真实commit。

## 从0.8.5升级到0.8.6

本次只更新面板展示和包版本：按固定commit及docs/releases/0.8.6.json核对并替换
companion_panel.html；vault.py版本辅助文件同步到既有发布器。runtime2.7.1/plugin0.4.0
保持不变，不重新执行上一节的情绪校准、不重装插件、不改学习记录、SOUL、渠道或任务。
按当前HOME_PANEL.md静默刷新同一资料库HTML，核对关键词分组、搜索、分页与横竖屏。
更新私库架构锁及简短当前说明，保留继承prompt，不恢复旧安装流水。禁止把调试写回日记。

## v0.9.0 可选小米睡眠与运动

按plugins/mi-fitness/README.md和manifest核对安装。用户明确选择后才接入：本机扫码、
一次性RSA3072公钥+AES-GCM密文附件交接；宿主凭据和按天健康缓存都在brain/工作区与
备份源之外。上游登录态不是细粒度官方OAuth，睡眠/步数/活动/锻炼白名单由受限适配器
实施，不提供独立心率/血氧/压力/体重/定位或通用SDK/MCP入口，不复制凭据到新Agent。
worker单独Python3.12+；核心既有plugin_context只读精简缓存，不加前置网络或模型调用。
更新原life30m任务正文，健康sync内置60m门禁，第一轮静默建基线，新睡眠/锻炼由同一
模型判断是否关心，01–07不主动分享。走真实主动消息/贴纸/回执入口，unknown不重发；
不伪造ct_life、健康情绪事件或虚拟经历。安装后核真实cloud读取、字段白名单、备份排除
和原任务身份不变。核心runtime2.7.1与阅读0.4.0保持；只更新版本辅助文件和架构锁。
