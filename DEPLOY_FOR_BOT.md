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
3. 当前回复模型读取companion_schema的48词表，直接填写prepare返回的emotion_template（v2/full48-v1），结合人设/事件/对象/责任/期待逐项提交48个变化量。同一源事件再次prepare写入并读回mood与本轮reaction，检查updated/unchanged/replayed及主聊pipeline_ok；invalid读取emotion_validation.detail修正同一源，不重新抽签。具体字段、幅度与六类摘要见MODEL_EMOTION.md；不能把missing/invalid或降级抽签当作评估成功。
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
