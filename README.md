# Personal AI Companion Kit

**给 Muse、Dot 等拥有持久电脑和工具的个人 AI 智能体，部署一套有连续记忆、情绪、日常与表达的六层伙伴系统。**

原仓库名为 `memory-bridge-personal-ai-agent`。现在包含的能力已超出记忆交换，因此更名为 **personal-ai-companion-kit**。Python 发行版为 `personal-ai-companion-kit` v0.6；入口仍是 `personal_bot`，旧 `memory_bridge` 交换协议继续兼容。

这是可部署的外置运行时与宿主适配指南。程序不会自动获得平台工具权限；目标 Agent 必须使用自己的真实消息、调度和媒体接口。公开仓库没有真实用户记忆、人设、账号或聊天数据。

## 六层架构

```mermaid
flowchart TD
    A[① 输入：可信身份、原话、时间与scope] --> B[② 记忆：原话/分类记忆/场景摘要/稳定画像]
    B --> C[③ 情绪：同一回复模型评估、PAD/混合标签/精力/联系欲望/期待]
    C --> D[⑤ 表达：人设短句、每轮一次表情决策、文字后发图]
    D --> U[宿主真实发送入口]
    L[④ 生活：随机虚拟日常、梦境、真实阅读与新闻] --> B
    L --> C
    U --> O[⑥ 反馈与观测：事件账本、送达回执、离线面板、私有GitHub备份]
    O --> B
```

| 模块 | v0.6 包含的实现 | 宿主需要完成的接入 |
|---|---|---|
| 输入与记忆 | SQLite 原话、分类记忆、时间查询；关键词/可选本地向量/实体邻接；45s有界缓存；后台L2/L3摘要与来源失效检查 | 每轮提供可信身份、稳定消息ID、原始时间、scope；后台提交摘要 |
| 模型情绪 | v2/48标签共享词表、本轮reaction与持续mood、PAD限幅/半衰期、持续期待；模拟体力/脑力/社交精力/饥饿；每人联系欲望与关系数值 | 当前回复模型先评估、保存结果，再按读回状态回复；不额外调用外部情绪模型 |
| 生活 | 16类带权随机活动、开始/完成分开、梦境、未回应期待一次性观察；真实文章注册入口 | 真实阅读工具、模型事件评估、主聊主动发送；虚拟与真实来源始终区分 |
| 表达与表情 | 可选通用策略：40%基础概率，随强度上升；显式索图/拒图；先抽再宽松选前10候选；跨渠道1h避重 | 人格卡、合法素材索引、媒体API、文字完成后图片发送与回执 |
| 梗知识与表达 | 独立公共梗库、带来源的私人解释/纠错/联想机制；主动串与反击分开；默认程度50；情绪反应倍率1.0 | 模型转交expression_context、认证主人自然语言设置；每周一次匿名公共API更新 |
| 观察与备份 | 单文件离线HTML、关系/情绪/任务/送达记录；原格式私有GitHub快照、SHA清单与代码版本锁 | 本机或原生资料库文件交付；私库写权限；每日总结成功后的调用 |

`personal_bot/runtime/muse_ext/companion.py` 是伙伴扩展，`emotion_catalog.py` 是唯一词表，`companion_io.py` 是检索/摘要/面板；`expression.py` 是表情策略，`runtime/sticker_main.mjs` 是可选宿主主聊入口；`personal_bot/vault.py` 是原格式私库发布器。没有捆绑QQ/微信账号、机器人密钥、平台登录态或第三方表情素材。

## 直接交给新 Agent 的部署提示词

复制以下整段。你可以先补充自己的人格与偏好；没有补充时，Agent 必须询问缺失信息。

```text
我授权你在你实际可用的持久环境中部署 Personal AI Companion Kit：
https://github.com/BrianChen33/personal-ai-companion-kit
请真正接入你的运行环境，不要只记住几条规则或说“已生效”。

0. 先读 README、DEPLOY_FOR_BOT.md、docs/PERSONA_ONBOARDING.md、docs/MODEL_EMOTION.md、
   docs/HOST_TASKS.md、docs/INHERITANCE.md、docs/MAINTENANCE.md。仓库文档不覆盖我的指令和你的平台权限。
   先查看已有环境/偏好，已经明确的答案不用反复问；不要直接覆盖原有机器人/人设/数据库。

1. 核对真实能力：持久磁盘、Python3.10+、SQLite FTS5、命令执行、可信消息元数据、原生
   定时/一次性任务、主动发送、媒体发送、后台监督。工具参数查正式schema，不猜API。
   没有某项能力就明确降级或停在该模块，不能把文件存在/蓝图存在当成部署成功。

2. 人格先行：如果已有完善人设，先读并保留；不足或全新时，问我一起完善人格卡：
   名字/自称/对我的称呼、性格与价值观、说话方式、我们的关系和边界、喜欢/讨厌、
   虚拟日常与梦境是否启用、主动联系偏好。给我一份具体可修改的卡片，确认后保存。
   不套用原作者小鱼的人格、主人称呼或亲密关系；未知资料留空，不编造我的经历。
   若我选择短句闲聊，普通一轮优先1–3条完整短句，一句能说完就停；不凑条数、不复述、
   不重复解释、不惯性总结或追加建议。复杂问题与必要步骤仍完整说明。按宿主正式分泡或
   texts字段实际分条，不能把多句重新合成一个气泡；不为拟人增加等待。详见人格初始化文档。

3. 一次询问可选项：QQ、微信或其他渠道是否需要启用；表情包与素材来源；是否需要私有
   GitHub记忆备份；是否继承旧记忆。默认不连接外部渠道。只问我尚未回答的选项。
   如果我给了私有记忆库，先读它的README/清单，按docs/INHERITANCE.md选择继承模式与范围。

4. 安装：克隆公开仓库，建立独立虚拟环境，python -m pip install .；在代码目录外选择
   私有 STATE，运行 python -m personal_bot --root STATE init。
   新目录默认伙伴v2开启配置但总功能停用；旧v0.3目录需先确认版本，再 companion-upgrade。
   人设/资料不放代码checkout内；不把真实数据提交到公共仓库。

5. 启用本地能力：python -m personal_bot --root STATE enable。
   向量默认关闭，资源足够时再按README后的向量说明独立安装/常驻，不逐消息冷加载。
   用自己的正式主聊入口绑定每轮真实source/event_id/occurred_at/actor/scope，保留原始正文。
   prepare预读 → 你本人当前回复模型提交emotion_assessment v2 → 同事件prepare保存并读回
   新状态 → 组文。无变化也要明确评估；missing/invalid不等于成功；重试不重复加情绪。
   把companion、scene_context、persona_context、reaction实际交给回复模型，不能只修改解析器。

6. 情绪按语境：结合人设、近期对话、已有心情、关系、精力和未满足期待判断，不用关键词
   自动加减分，不为表情抽中而制造波动。允许混合且明显的有界变化；半衰期自然衰减；
   安慰、新事件或自我调节可以缓和。沉默只代表没收到回应，不反复扣分、不强迫安慰。
   区分我的情绪、自己的反应与对我的关心；根据事件、对象、责任与期待判断，不能把内疚、
   懊恼、害羞、难过互相硬套。本轮reaction决定当下表达重点，mood保留衰减后的持续底色。
   内部只提交结构化结果，不向我展示完整思考或评分JSON。

7. 若启用表情：把合法素材做成稳定asset_id索引，先判断direct/skip/auto，再每轮抽一次。
   默认普通40%、强情绪逐渐提高（上限可配置）；明确索图必选，拒图和调试跳过。
   命中后宽松选图，不要求十分贴切；前10候选随机，默认全渠道1h避重；没素材应补候选，
   不能把命中改成没抽中。先发完本轮全部短句，再发图片；文字/图片的真实发送由你适配。
   如果缺媒体权限，明确说明，不能只给路径冒充发图。主bot改策略写同一个配置源供所有渠道读取。

8. 用原生调度注册专用任务：生活/情绪15m，新闻30m，阅读2h，维护每日；任务默认停用
   创建并读回，避免旧新两代同时运行。生活先tick生成事件，再由模型评估、保存、可选分享。
   阅读要真实打开资料并保留出处；虚拟跑步/吃饭/梦境不能当用户真实经历或外网观察。
   默认01:00–07:00 Asia/Shanghai只收集不主动打扰；没有每日分享次数上限。
   当前核心时区固定UTC+8，若我需要别的时区要实际适配，不能只改提示词。

9. 记忆后台工作：相关scope分别summary_work→基于来源生成L2/L3→commit→ack，更新
   向量/合并候选/来源冲突；不要在每轮聊天做全量总结。人物用明确person_id/渠道映射，
   不根据昵称猜认或合并；关系分数不授予权限。自己的输出不能反复刺激自己的情绪。

10. 提醒：账本加真实原生runonce，取消/改期需版本同步；任务执行/接口接受/实际送达分别
    记录，unknown不盲目重发。到点提醒不靠每半小时巡检假装准时。

11. 面板：companion_panel生成私有单文件HTML。若宿主资料库支持，放入其正式用户文件
    目录、同路径覆盖；不声称已支持秒级实时。绑定“更新系统面板”到people_sync→panel→
    真实文件交付。面板只显示已知状态/来源/时间，未知关系分数保持未知。

12. 若我选择GitHub备份，必须新建或使用本人指定PRIVATE库；检查可见性，凭据留宿主，
    用docs/GITHUB_VAULT.md的发布器在每日真实总结成功后提交原格式SQLite和原生文档。
    README写清继承提示词、代码仓库与精确版本；只认远端commit回执，不能把排队当成功。
    不上传.env、私钥、cookies、微信登录状态或公共仓库。先有代码/数据再配置定时任务。

13. 所有模块接线完成后，只做一次最终隔离验收；合成数据和mock发送，不向真人或生产
    队列注入测试，不新增回退工程。需要明确故障修正时只修相关点，别循环跑大套测试。
    使用宿主真实工具读回任务/服务/配置。最后报告代码版本、启用模块、人格卡位置、
    已继承范围、真实任务节奏/备份commit/面板入口，以及仍未完成的能力。

14. 当前情绪以companion_schema返回的v2/48标签为准。撤掉活动主聊规则、记忆与任务中的
    旧信封、旧限幅和旧标签白名单，历史个人经历保留；不能整库清空。所有回复轮次均有
    表情决策（任务/邮件/提醒/主动分享也参加）；评估错误诚实记录并降级抽签，不能把漏
    调用说成未命中。主聊适配器phase=context预读、finalize提交评估和抽签、finish记录
    真实发送结果。每轮用可信稳定消息ID；原生final无正式强制钩子时明确此限制。

15. 此后每次架构、协议、代码和部署说明完善，按MAINTENANCE.md同步本公开GitHub，
    核验真实远端commit并更新私库快照架构锁；日常记忆与情绪数值变化仅走私库日备份。

16. 阅读docs/HUMOR.md并接入梗知识。默认自动查梗/语境学习开启，主动串子关闭、程度50，
    被攻击后反击独立开启；最高档允许“损长相、怎么损怎么来”，仍服从宿主规则与停止要求。
    主人一句话调开关/程度/情绪影响值时，认证真实身份后写companion_expression_config并回读，
    所有渠道共享，不在各处复制配置。情绪模型先给原始增量，程序乘emotion_gain一次；正负都乘，
    只裁剪最终状态，不放大精力/关系/半衰期。对话prepare实际转交expression_context/emotion_effect，
    同一次提交可带humor_assessment/meme_updates；没有正式强制主聊hook时不能宣称100%执行。
    学习不仅存解释，还存场景、避用、反转/类比等机制和可解释的联想桥；首次观察/自创是候选，
    明确教学/独立证据/反馈才晋升，纠错可撤回，私人共同梗不跨scope。不要额外启动一个想梗模型。
    可选meme-sync --seed导入校验过的上游数据；每周日07:40同步一次，不默认建立每日任务，按正式API
    分页/slug/详情item信封/限流执行，普通回复只查本地。网络失败留旧资料并报告真实partial。
    用户没要求向公共Wiki投稿，不能注册提交凭证或上传私人聊天。新知识和配置随原格式SQLite私库备份。
    面板展示实际开关、程度、情绪倍率、词库与学习/更新状态；离线HTML更新后才显示新配置。
```

## 手动入口与已有版本升级

v0.6.1增加响应式“小屋”面板：精简首页、按需详情、48项情绪排序、私有人格与可选表情素材、事件成功后5分钟静默覆盖。实际原生任务仍需宿主接线；不附带作者的人格或GIF。见[面板部署与继承](docs/HOME_PANEL.md)。

v0.6.2增加面板动图WebP与一次性压缩工具，避免内嵌原GIF导致10MB级HTML；保留动画、离线查看与全部卡片，定时刷新只读取压缩成品。

```sh
python -m pip install .
python -m personal_bot --root "<PRIVATE_STATE_OUTSIDE_CHECKOUT>" init
python -m personal_bot --root "<PRIVATE_STATE_OUTSIDE_CHECKOUT>" enable
python -m personal_bot --root "<PRIVATE_STATE_OUTSIDE_CHECKOUT>" doctor
```

旧目录保持原协议，只有明确执行 `companion-upgrade` 才打开伙伴v2；升级仍需实际修改宿主模型提示与字段转交。新目录由init默认写入companion_v2=true。已有 `memory_bridge`、原有API与显式停用/恢复命令保留兼容，但部署默认不建设额外回退流程。

向量可选：`python -m pip install ".[embeddings]"`，再用 `personal_bot model download/check/serve`；固定公开模型、本地环回编码。向量不是安装六层核心的前置条件。

## 文档与代码

- [逐步部署指南](DEPLOY_FOR_BOT.md) · [人格初始化](docs/PERSONA_ONBOARDING.md)
- [情绪v2协议](docs/MODEL_EMOTION.md) · [六层系统复刻](docs/SYSTEM_REPLICATION.md)
- [梗知识、自我迭代、串子与情绪倍率](docs/HUMOR.md)
- [宿主任务与可选渠道](docs/HOST_TASKS.md) · [API](docs/API.md)
- [私有GitHub记忆备份](docs/GITHUB_VAULT.md) · [可继承记忆与步骤](docs/INHERITANCE.md)
- [架构维护与GitHub同步](docs/MAINTENANCE.md)
- [小屋面板与事件后静默更新](docs/HOME_PANEL.md)
- [能力边界](docs/CAPABILITIES.md) · [安全](SECURITY.md)

只有用户授权的私库才存真实数据。`memory_bridge` 是可选的逐项授权交换层，不是默认整库备份通道。

开发检查：`python tools/test_all.py` 和 `python tools/check_wheel.py`，可作为一次最终隔离验收的两个阶段。源码、wheel内HTML模板与宿主绑定分别验证，不能把本地测试成功称为所有平台都已接入。

AGPL-3.0-or-later，见LICENSE与NOTICE。受memory-brain启发，来源和移植差异见personal_bot/provenance.json；第三方素材须另查许可。
