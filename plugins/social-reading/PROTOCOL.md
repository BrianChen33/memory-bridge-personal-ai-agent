# 唯一宿主协议 · social-reading0.3.0

先读实际宿主工具schema。下列是本地brain.py请求，不表示Muse自动注册了新工具：

```json
{"op":"plugin_call","scope":"owner-private","plugin":"social-reading","action":"status"}
```

管理和反馈只供可信主人/本地管理员适配器，scope不能代替身份验证。先schema取模板；
分别看action/status/reading_saved/pipeline_ok，外层ok不代表网页读通。不默认新建任务。

## 安装与来源

- onboarding：机器人安装后自己问主人；onboarding_sent(receipt)只记录真实发出的原生消息。
- source_add(input,owner_event,authorized=true)：input必须是该真实主人原话中的链接/吧名。
  名称仅生成pending；链接限定官方HTTPS贴吧/f?kw=...。
- source_verify(source_id,status,url,observed_name,title,receipt)：verified要求实际同名页面和
  原生工具回执；blocked/login_required/unavailable/failed保留真实障碍。安全验证白屏不是成功。
- source_revoke(source_id,owner_event,authorized=true)：撤销后旧租约不能提交。
- configure(owner_event,authorized=true,patch)：修改auto_browse、language_learning、分享阈值、
  预算或抽样/截断，并回读值。owner_event是正式capture/prepare取得的整数ID，不是示例ID。

## 一次真实阅读

1. 在既有生活/阅读任务中决定本次逛帖，plan(job_id=真实原生运行ID,manual=false)。
   manual=true仅限主人此轮明确要求，不用于绕过安静时段。awaiting_sources不启动浏览器；
   awaiting_verification暂停；busy/run_budget_used/paused结束。quiet_hours只收集、不主动分享。
   不得换job_id规避限额。
2. action=browse后，只用真实browser.browse按返回URL/profile/预算阅读。可在可见界面选择
   最新/最热/精华。discover(lease_id,receipt,threads)接收最多50项url/title/author/is_top/replies。
   列表发现不等于读完，不产生情绪。
3. 进入实际列表中的帖子，逐楼保留正文、楼中楼及图片对应关系。未知字段null/空字符串，
   不用下标编楼号。图像仅有外链时url_only，确实由工具看过才viewed及描述。不另起浏览器抓图。
4. observe(lease_id,observation=完整schema对象)。provider=tieba、schema=social-observation-v1，
   含forum_url/url/title/tool=browser.browse/receipt/status/coverage/floors。coverage分别给
   pages_seen、total_pages或null、ended、all_visible_floors、实际next_url或null。只有前2楼就是
   partial；达到预算/总量未知都不是全文。单包≤50KB/120层，长帖分轮，plan.resume保留进度。
5. 同一租约同内容重试replayed；成功后换正文conflict，不换ID重抽/重复感受。
   blocked/login_required等不生成阅读事件。成功返回document_id、source_event、quote_id。
6. read(document_id)读有界抽样；source_event真实actor=article，来源plugin:social-reading:URL。
7. 同一模型reflect(document_id,summary,lexical_candidates,style_candidates,growth_candidates)。优先提取
   最多8个具体词/短句，另最多3个表达机制；字段及旧候选迁移见docs/VOICE_TRIALS.md。
   lexical项含kind/form/meaning/understood/reason/example/evidence_quote，词或变体及短引文必须
   在真实记录中。已理解即trial，不等3篇帖子；不明确的含义保持candidate并说明原因。
   usage_mode=reference_only只保存释义，不投影为口头禅。已有同一表达用existing_id，别反复建同义项。
   personality_growth开启时，再问自己这段经历是否让我认同/反思某种偏好或性情；可无变化。
   growth_candidates最多2项：domain=preference|temperament、trait、interpretation、example、
   evidence_quote、resonance(0<值<=1)、direction=adopt|reconsider、已有项existing_id。先读status
   合并同义项。按docs/PERSONALITY_GROWTH.md执行，不用关键词决定人格，不额外调用模型。
8. 同一模型appraise(document_id,interest_score=0..100,emotion_assessment=full48模板)。
   评分考虑主人兴趣、真实内容和新鲜程度；assessment.share表示自己是否想分享。运行时再检查
   阈值/许可/启用状态。pipeline_ok=false读取具体错误修正同源；不额外启动情绪模型。
9. 既有情绪任务先用pending取得待评估document_id/source_event/实际摘录和full48模板，
   plugin:social-reading来源走appraise，其余虚拟/梦境保持原流程。
   发送仍用companion_share的claim/实际发送/settle；claim前会重查插件/许可/阈值。
   quiet01–07按核心规则；不要在任务结尾强行报告。缓存重放不算新阅读。
10. 正常聊天转交最新current_persona及其growth_overlay、expression_context.learned_voice与
    plugin_context。成长与底稿及当前情绪共同构成现在的人格，可修正旧可变倾向；不能说只影响
    措辞/永不影响人格。外观、身份、真实历史与权限仍保留，按语境自然取用，不每句套用。
11. 自动逛帖由生活40/60抽签产生手机意图；从companion_tick.phone或companion_phone取
    actionable=true的request.id，plan传life_intent=id。运行时固定job_id=life-phone:<id>，
    不另一次抽签，不再由2h任务独立选刷帖。手机意图不等于已读；observe真实成功才标read。
    手动明确要求可用原manual入口，不计自主生活比例。参阅docs/LIFE_ROUTINE.md。

v0.3.0优先用finalize_reading(document_id,summary,lexical_candidates,style_candidates,growth_candidates,
interest_score,emotion_assessment)一次完成上述reflect+appraise，然后检查complete。
growth开启但无变化也填growth_candidates=[]。completion(document_id或lease_id)只读核对
真实观察/反思/full48/兴趣/成长审视，缺项修同一document，不能强制增加文档计数。
分享本轮帖子时主聊commit带reading_documents=[真实document_id]，见docs/MAIN_ENTRY.md。

## 反馈和继承

主人纠正新说法时按语境关联habit_id，调用habit_feedback(habit_id,owner_event,authorized=true,
kind=meaning|context|tone|stop,correction=按类型字段)。词义/场景/语气纠正不一概封禁；明确stop
及旧接口negative/stop保持停用，后来的帖子和别名不自动复活。主人纠正优先于后续曝光。
旧candidate先habit_review读取真实档案，再由同一模型逐项判断；可用learn_expressions补提具体词，
不能批量SQL晋升。teach_expressions只接真实主人教学事件，不伪造帖子来源。

普通context只取最多6条有界voice_overlay，给新trial留位置。现有15m反馈任务的原生feedback阶段
保留必要真实assistant项，交observe_outputs；再usage_work取最多3条，由同一模型判断实际采用
是否合适，以record_use(habit_id,output_id,evidence_quote,appropriate,reason)记账。
解释词义、引用、调试不算采用。真实合适使用3次、跨2轮即mature；不要求主人表扬，不增加来源可信度。
personality_growth开启后，同一任务habit_growth_work→模型反思→habit_growth_integrate，稳定习惯
可进入长期偏好/性情，与原成长共享预算；不能按词频推导信念。无需新模型、新定时任务或前置回复流程。
见docs/VOICE_TRIALS.md及docs/PERSONALITY_GROWTH.md。
SQLite含sr_表和来源/反馈；plugins.json含启用信息。先重建锁定版本插件，再选择性继承；
旧任务/登录状态不自动激活，撤销来源不删除已学历史，停止某习惯用反馈接口。

## 环境对照验证 · 2026-11-06

原npm0.3.5与commit568cc4d的core.mjs一致，隔离安装成功。但独立浏览器启动失败，退出码1，
未发出贴吧请求，不能将其归因于贴吧风控或称原版读取成功。未下载额外浏览器。
原生browser.browse对同一公开列表返回“百度安全验证”白屏，无帖子。登录后的帖子、楼中楼/
原图尚未在线验收。有正式用户接管窗口完成正常登录/验证的方式，本次未操作。
任意JS/独立截图/下载API未暴露；browser.open与live browser登录态不同，不能混称同一会话。
