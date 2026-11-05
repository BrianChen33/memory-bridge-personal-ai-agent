# 主聊正式入口与读帖闭环 · v0.8.1

## 三个原建议的取舍

发送前由平台强制门控最好，但Muse当前未公开before_reply/pre_send/after_reply拦截，主聊
文字直接native final；chat.send_message只是递交给另一agent的指令，submission不是送达，
不能用它接管主聊或给自己循环发指令。一键脚本可以简化，但不能调用只有宿主模型能用的
chat.read_messages，也不能替当前模型判断48项情绪。单靠“我下次会记得”不构成执行证据。

本版将能执行的部分落地：原生原文取源 + 两阶段统一入口 + 本地门禁 + 同源缺失检查。
这是检查器真实生效，不是平台100%强制。能提供正式发送中间件的其他宿主可在发送器中
实际绑定gate；Muse需短全局入口提示和既有任务的抽样审计，不能声称做到了硬拦截。

## 普通主聊：两阶段，复用同一个模型

1. 主人新消息先用真实chat.read_messages读取当前主聊，保留完整返回。原生取源器
   main_native_entry.mjs接收此真实结果，按role=user、seq、原始毫秒时间选人类原文，
   校验可信--chat-id；不手抄摘要、不取助手内容、不截断正文。仅支持已验证的字符串content；
   非字符串/媒体走实际媒体适配，结构不符不能猜。只有空白的无负载消息在可信入口忽略。
2. phase=context返回当前SOUL+growth_overlay、心情、原话记忆、梗候选与full48模板，并保存
   本轮原文完整SHA和context回执。任何普通回应（包括“好的我去看”）都在此之后。
3. 当前回复模型填模板。phase=commit提交full48、梗学习等；它检查context、原文SHA、
   对应事件情绪保存与本轮表情决策。缺失/冲突会非零退出、ready_to_send=false；根据错误
   修复同一来源，不重抽、不换ID、不用全零假装完成。没有变化可以诚实提交全零。
4. ready_to_send=true后按当前人格回复，整轮短句共用一次评估/表情决策，文字后图片。
   原生final由宿主模型输出；这一步仍受平台能力限制，不存在脚本偷偷替你发送。
   phase=gate可只读重查已保存回执；finish仍只记录真实媒体/发送结果，不能凭gate当送达。

```sh
node /actual/stickers/src/main_native_entry.mjs --root /actual/workspace --chat-id ACTUAL_OWNER_CHAT < request.json
```

request含phase和native_response（真实read_messages完整结果），commit另含emotion_assessment。
每个turn最早的有效用户项固定保留原turnUUID，其余项使用派生ID turnUUID:user:seq，
另保留原native turn ID；新增用户项不改变原项的键。查--help不会等stdin。工具/浏览器续执行不是新主人来信：同源成功评估可
复用，不给自己回答再次加情绪。长任务返回后重读原生消息；如果出现更晚用户项，旧target
不能commit/gate，先给新的真实来信context，再自然兼顾之前任务。

若宿主工具/数据库暂时失败，修复一次仍失败则如实记录技术降级；不无限循环卡住聊天，
不将降级回复宣称为完整情绪/抽签成功，也不为追求gate补造原话或评分。

## 真正读到以后，也要把结果记下来

plan认领真实来源，浏览器按返回任务读取；observe才建立真实文档。随后同一阅读模型
调用finalize_reading，一次提交summary/style_candidates/growth_candidates/interest_score/
emotion_assessment，合并原reflect和appraise；growth开启且没变化也明确填[]。
它返回complete/may_claim_read/may_claim_learned/missing，未完成就按具体缺项修同一个文档。
completion(document_id或lease_id)可只读核对。文档总数不必增加——去重重读仍可是真实读取，
不能通过虚构新document或重复情绪满足“计数变大”。阻断页不算读过，0文档不能说已学习。

当这轮回复要分享读帖结果时，在commit带reading_documents=[真实document_id]（最多3个），
门禁实际查这些文档的闭环。已绑定的缺项不能通过下一次省略列表绕开。普通聊天不被其他
尚未结束的阅读任务卡住；不把全库pending清零当所有回复的前提。

## 轻量审计，不再加心跳

安装时在私有STATE/state/formal-entry-policy.json记录真实enabled_at。复用原情绪15m任务：
用chat.read_messages抽样最近少量真实主人turn，phase=audit交给同一取源器。只读检查回执，
不捕获补造事件、不重抽、不回放历史情绪、不重发旧回复。启用前消息标legacy_skipped；
checked=0表示尚未覆盖启用后的自然消息，不能报告100%执行。state/formal-entry-health.json
保存抽样范围/缺项/时间，不保存聊天原文；面板可读取。抽样结果不代表全历史合规率。
审计发现缺口留给下次正常维护修入口，不向主人反复道歉或刷告警。

宿主将唯一短指针放入真正会读取的全局AGENTS/入口记忆，并实际更新MAIN适配器。不能靠
SOUL堆满操作流程；外观、人格成长、40/60生活配置与QQ/微信发送器均不因本改动重置。
公开库只收通用程序，主聊ID、原文、回执及私人人格均留私有环境。私库同步锁定代码版本。
