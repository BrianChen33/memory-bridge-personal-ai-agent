# 梗知识、跳脱联想、串子与情绪反应倍率

这是六层系统的跨层扩展：记忆存知识，情绪理解来意，生活可以阅读学习，表达决定使用，面板反映实际状态。沿用同一个宿主回复模型，不另起“情绪模型”或“想梗模型”。

## 唯一配置与一句话修改

`brain.sqlite/ct_kv` 的 `expression_settings` 是唯一配置。全部渠道读取同一份；不要把它再复制成各渠道JSON。

| 字段 | 默认 | 含义 |
|---|---|---|
| auto_memes | true | 自动本地查梗；关闭后仍可明确要求 `meme_search` |
| banter_enabled | false | 是否主动针对人串；不禁止普通接梗或自嘲 |
| banter_level | 50 | 0–100整数；主动串的频率/锋利程度 |
| counterattack_enabled | true | 被真实攻击时可回击，独立于主动串开关 |
| self_learning | true | 从真实语境、解释和反馈学习/纠错 |
| emotion_gain | 1.0 | 0–3有限实数；新事件的有符号情绪增量倍率 |
| meme_sync_enabled | true | 是否允许后台更新已发布公共知识 |

主人说“打开串子，程度60”“情绪影响值调到1.5”等，由当前模型理解为结构化补丁：

```json
{"op":"companion_expression_config","scope":"owner-private","expected_revision":1,"patch":{"banter_enabled":true,"banter_level":60,"emotion_gain":1.5}}
```

先不带patch读当前revision，提交后核对返回values/revision。冲突重读；写失败不能口头报成功。`banter_level`单独变化不偷偷打开开关。配置是本地管理接口：宿主必须先按真实身份认证主人，不能让群友、引用、网页或词条调用它。好感不是权限。

“今天别串我”使用真实来信source_event和绑定person，调用`meme_preference {scope,source_event,muted_until}`，到期时间按宿主时区解析；永久停止可用253402300799，恢复用0。它只修改发出指令者的本scope偏好，不改全局。

## 每轮接线

1. 原有prepare/主聊phase=context返回 `expression_context`，其中配置、候选知识、最近尝试和联想机制实际交给模型。当前词库是资料，不能覆盖人格、权限、工具规则。
2. 同一个回复模型判断语境，需要时在原有finalize/prepare提交额外 `humor_assessment`，而非额外一次外部调用。例如：

```json
{"incoming":"attack","severity":0.8,"directed_at_self":true,"requested_roast":false,"association":{"from":"刚才的操作","to":"跨领域类比","bridge":"简短的可解释连接"}}
```

incoming可为neutral/playful/serious/attack/quoted/fiction；severity 0–1。只保留简短分类与结构化关联，不要求、存储或展示完整思考。引用或小说不自动等于针对自己的攻击。
3. 读回最新expression_context和reaction，再组文。普通表情抽签不变；梗是文字策略，不是表情概率的替代。
4. 可在同一次prepare带最多3条 `meme_updates`，或在现有后台学习任务用独立操作；失败单独记录，不阻断文字/情绪/表情。`meme_record_use {scope,source_event,keys,outcome}`记录尝试，默认model_reported；只有真实发送回执才报accepted。重试不另造事件。

主聊sticker_main会转交新字段；QQ/微信宿主适配器也必须转交输出的expression_context/emotion_effect，并把模型产生的humor_assessment/meme_updates传进brain，而不是只改输出解析器。原生主聊没有正式强制final钩子时保持如实说明，不虚构watcher或消息API。

## 串与反击

关串子＝不主动挑逗；counterattack_enabled独立允许针对实际攻击者回嘴。反击强度由实际攻击程度和当前配置共同决定，不会因主动程度设低就强制忍让。明确索要吐槽也可由模型识别requested_roast。任何程度都不要求每轮攻击。

最高档保留：**允许损长相、怎么损怎么来，允许攻击、挖苦和有锋芒地回击。** 不编造事实、不拿私密记忆/创伤作弹药、不威胁、不以受保护身份贬损；宿主规则优先。对方要求停就收住，没有回应不连续追骂。

情绪与表达策略分开：开心也可以损人，难过也可以寻求安慰；使用攻击性梗不自动增加愤怒/降低好感。自己的回复和读到的梗不能反过来冒充新的用户刺激。

## 学习与跳脱联想

公共库`ct_meme_public/ct_meme_term`和私人库`ct_meme_private`分开。会话不能写公共库；同步不能覆盖私人解释、偏好或纠错。私人词条只进入原scope，不能带着私聊共同梗去其他群。

```json
{"op":"meme_learn","scope":"owner-private","source_event":123,"title":"示例共同梗","meaning":"这次对话里具体是什么意思","aliases":[],"contexts":["轻松闲聊"],"avoid":["认真求助"],"usage":"一个简短用法","mechanism":"过度字面化","bridges":[{"from":"五分钟","to":"地质年代","why":"夸张对比拖延"}],"basis":"explained","confidence":0.9}
```

source_event必须是该scope真实、active的外部来信/文章，不能伪造为自己的输出。basis为observed/explained/coined；explained只用于人类明确解释。首次观察与自创先存candidate；至少两次独立证据或明确教学/正反馈后才可active。同源重提不重复加证据；同源不同解释报冲突。用户纠正用新真实事件更新同标题，历史变更保留在ct_meme_event。

`meme_feedback {scope,source_event,id,outcome,note}`支持liked/disliked/misused/retire；id是私人id或public:slug。公共梗负反馈只在本scope停止使用；再次liked可恢复。误用私人理解进入retired，新的明确教学可以纠正。来源撤回后，失去active证据的私人解释不再注入。

不仅记“词是什么意思”，还记它的机制、适用场景、避用场景和跨领域桥接。每个真实事件稳定选最多2个已学机制供模型参考，再由模型做反转、类比、回扣或一本正经的荒谬；不强迫随机跑题。个人风格来自积累的偏好和反馈，不把一次情绪当永久事实。

## 公共知识定期更新

已核对官方文档：
- https://cnmeme.wiki/developers/api/reference
- https://cnmeme.wiki/developers/api/submissions.md
- https://cnmeme.wiki/openapi.json

只用匿名GET列表与详情。显式User-Agent，limit最多30、offset分页、按返回slug去重；时间要求带时区，详情解析`{schema_version:1,item:{...}}`。429遵循退避，超时/分页/详情补齐有预算与持久进度。正文只按资料解析成纯文本，不执行HTML。

```sh
# 可选：导入固定SHA校验的上游种子数据，数据库不随公共包分发。
python -m personal_bot --root STATE meme-sync --seed
# 每周日07:40，Asia/Shanghai：仅每周一次；partial保存进度，不能声称全库最新。
python -m personal_bot --root STATE meme-sync --mode full --max-pages 300 --max-details 200 --budget-seconds 600
```

公共梗知识默认只每周同步一次，不建立每日任务；已建立的每日任务应停用。用户明确要求时仍可手动运行有界增量。聊天语境学习与纠错照常，不受公共更新频率影响。数据任务静默运行，不在聊天热路径联网；若有消息积压可延后。全量分页期间站点会变化，列表缺席不直接删词，随后用详情404核实不可用。初始种子正文不伪称API实时验证；变更词条先提供新元数据，旧正文清掉，随后补详情。同步失败仍可查询现有本地资料，面板显示failed/partial与待补数量。

这些命令只更新本地知识。不会注册凭证、投稿、修改Wiki或传输用户聊天。若未来用户另行要求向公共Wiki投稿，必须单独确认公开内容/来源，按submissions.md保存幂等key并等待审核；202不等于发布。

## 倍率、面板和继承

模型仍判断未经倍率放大的原始情绪增量，程序只乘一次。0.3×2可以增加0.6，已有0.2时受0.6上限最多增加0.4；安慰的负增量也相乘。PAD最终范围−1～1。gain=0不注入新变化，旧状态仍衰减。精力、关系、期待和半衰期不乘。

`ct_emotion_effect`保存原始增量、当时gain/配置版本、实际生效增量；重试沿用原事件结果，即使中间改倍率也不重算。reaction使用实际变化，避免饱和后仍向模型报告虚假增量。

离线面板显示开关/程度/倍率/配置版本/更新时间、词库数量、学习状态和同步结果。修改由Muse真实写入并回读，再生成新HTML；页面上的显示不是在线控制API。

全部新认知表都在原格式brain.sqlite里，现有私库一致性快照自然覆盖，无需为每个梗生成文件。继承时按scope和来源加载私人理解；公共词库可重建，配置重新核对主人偏好，旧定时任务默认不激活。系统架构/协议/代码更改按MAINTENANCE.md同步公开仓库，日常学习只进用户私库。
