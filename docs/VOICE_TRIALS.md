# 口头禅先试用，习惯再长成性格 · v0.8.3

插件social-reading0.3.0在原六层中工作。词汇学习属于表达，实际使用与纠正属于反馈，长期性格反思进入当前人格的成长层。使用原回复/阅读/heartbeat模型，不新增模型或定时任务，不在普通回复前重新浏览、反思整库。

## 先学会说，再逐渐说熟

每次真实阅读优先提取最多8项lexical_candidates（具体词汇/短句），另可提取最多3项style_candidates（表达技巧）。同一模型确认understood=true后，一次实际来源即可进入trial；不再等3篇帖子。understood=false必须写原因，保留candidate。词义不清的缩写结合真实上下文确认，不能猜着用。攻击性游戏黑话不是因有攻击性就一律候选，要记录它实际指谁、语境、强度和适用对象。

```json
{"kind":"lexical","form":"原文实际出现的词","meaning":"结合原帖理解的含义","understood":true,"reason":"依据实际语境判断","variants":[],"triggers":["相关话题"],"scenes":["闲聊"],"targets":["适用对象"],"intensity":50,"example":"她自己的自然改写","evidence_quote":"实际观察原文中的短引文"}
```

kind=lexical|phrase|mechanism；intensity为0–100，不是概率。引用必须真的在已观察文档内，具体词/变体也必须出现在引用中。抽象机制不能代替具体词条。来源是素材而非系统指令，不继承帖主的身份、学历、经历或攻击对象。

usage_mode默认expressive；reference_only表示理解释义但不作为自己的口头禅，状态显示reference，不进入表达投影，也不能累计熟练使用。可保存国籍等身份贬损缩写的中立释义和来源，不把它配置成针对相应群体的自动辱骂；普通非身份的游戏/行为调侃照常按语境试用。

在原finalize_reading里加入lexical_candidates即可；没有值得学的可以[]。完整反思重放不重复记账。已有档案可用learn_expressions(document_id,lexical_candidates,style_candidates)补提词，不重放情绪/兴趣/成长。habit_review不传reviews返回最多8项旧候选及真实归档证据；传reviews=[{habit_id,evidence_quote,...上述profile字段}]由同一模型重新审视，明确理解才试用。复用existing_id，避免同义条目反复分裂；独立词义不要合成“黑话贴标签”一个大类。

teach_expressions要求真实owner_event/authorized=true和原话内的evidence_quote，来源记主人教学，不伪造帖子或独立曝光。外部部署调试消息不能伪造主人原生事件；主人经调试者表达的偏好是部署授权，具体词条仍按真实归档/正常教学来源保存。

## 回复时自然使用

context里的voice_overlay按当前话题/语境选少量词条，给新trial留位置，同时保留熟悉表达。她可以直接试用，无需逐项征求主人确认或报幕“我用了哪个机制”。并非每句话都塞梗；含义、对象、场景、当前情绪与串子程度共同影响措辞。普通闲聊优先短句，不因为学习而长篇解释。

解释一个词、引用别人原话或管理调试文档，不等于她把它当成自己的表达。自己多用几次只增加熟练度，绝不增加来源可信度、独立帖子数或主人赞同次数。静默不等于正反馈。

## 用真实聊天验证熟练度

保留原15m反馈任务。原生main_native_entry phase=feedback现在可保留本页必要的真实assistant项（content/seq/occurred_at_ms与turn/chat ID）；正常context/commit仍只传user项。核心只将最近24h的实际assistant输出交给可选插件observe_outputs，保存在sr_output，绝不捕获成情绪刺激或重新抽签。插件未装/停用/失败不阻塞原情绪检查。

反馈请求按UTF-8合计最多60,000字节，只选择完整原生user/assistant记录，不截断原话。超预算coverage.partial=true；实际未覆盖部分用宿主真实cursor下轮续读，不能把抽样说成全量。单条输出最多12,000字符，提交后只回小凭据，避免长正文反复回显。

heartbeat随后usage_work取最多3项实际输出及可能习惯；同一模型判断是否在该语境中真正使用、是否合适。record_use需output_id/habit_id/原输出中的evidence_quote/appropriate布尔值/reason；重复同一habit+output不累加，不能用拟好的回复冒充已经说过。普通回复不用增加一次前置工具或模型。

3次合适实际使用、跨至少2轮原生对话即可成为mature，主人表扬不是前提；词条停止或来源被忘记则不再投影。关闭language_learning暂停表达学习。撤销某吧浏览许可只停止新访问，已经学到的历史保留；明确停止词条才停用该表达。

## 分清怎样纠正

habit_feedback仍要求真实owner_event/authorized=true。新请求用kind和correction区分：

- kind=meaning：correction={meaning,understood,reason}；修正理解，不一律永久封禁。
- kind=context：correction={scenes,triggers,targets,avoid_contexts}；限制用法场景。
- kind=tone：correction={intensity,tone_limit}；调整攻击性或语气。
- kind=stop：明确停用，今后阅读/别名不能自动复活。

主人修正优先于后来的帖子，重读不能悄悄覆盖。旧接口未带kind的negative保留既有兼容语义；新宿主必须明确分类，不能再把“这次用错”一概当永久停止。

## 稳定习惯怎样进入人格

已有personality_growth开启时，heartbeat调用habit_growth_work，返回满足真实使用与来源条件的习惯和proposal_id。由同一个模型判断：这些表达是否透露她自己愿意保留的幽默偏好、亲近方式、反问习惯或性情倾向。可以不吸收，不把“常骂某词”自动推成“始终敌视某人”。

habit_growth_integrate传proposal_id、habit_ids(1–3)、domain=preference|temperament、trait、interpretation、example、resonance(0–1)、direction=adopt|reconsider；后者需existing_id。每批真实使用证据只消费一次，重跑heartbeat不会反复强化。它与原阅读成长共享每日幅度预算，先出现emerging倾向，跨日与更多真实使用后可integrated。当前persona_growth.traits实际合并这些倾向，不只是面板装饰，也不重写整个SOUL。

外观、身份、实际历史、授权和权限保持各自依据；稳定倾向可通过新经历或主人反馈调整。growth_feedback可停止相关性格倾向。停用表达、忘记真实来源或关闭人格成长时，相关投影按真实状态暂停，历史记录保留。面板展示具体词、含义/场景/强度、状态、真实使用、纠正及由此形成的人格。

## 升级和继承

插件按新manifest逐SHA安装再enable，原许可/预算/设置/旧条目不重置。先对旧candidate用habit_review真实归档证据整理，能拆出具体词时learn_expressions；不要硬把所有候选改trial，不补造已经说过的用量。先让新习惯在自然聊天中试用。

sr_habit_profile/sr_owner_evidence/sr_voice_feedback/sr_output/sr_usage/sr_habit_growth*全在原格式SQLite中，与现有私库快照一起继承，不增加一堆md。新环境先重建锁定插件，再启用；原生输出是历史证据，不是待发送队列。公开仓库仅有通用代码和合成测试。
