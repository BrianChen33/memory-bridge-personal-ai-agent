# 生活琐事与刷手机 · v0.8

每次开始新的自主活动时先抽大类：默认生活琐事40%、刷手机60%。这是选择概率，
不是每个heartbeat都抽，也不保证十次恰好六次、更不是每天占时60%。当前活动未完成
不打断；夜间新活动仍遵守原规则。琐事再从散步、做饭、学习、音乐、整理、午睡、点心等
原活动池按时间/精力/饥饿及避重权重选择。

可信主人说“手机改成70%”时，宿主调用并读回：

```json
{"op":"companion_life_config","scope":"owner-private","patch":{"phone_probability":0.7}}
```

另一项自动变30%。拒绝非有限数、布尔值及0..1以外值；群友不能改主人的配置。
原生接口由可信宿主做身份验证，owner-private这个字符串本身不是登录凭证。
SQLite ct_kv.life_routine是唯一配置源，私库自动保留；面板日常详情显示两项比例。

## 刷手机是实际阅读入口

companion_tick抽中后生成刷手机活动与phone.request.id（虚拟拿手机动作，不代表读过）。
原生生活/情绪任务在同一次运行中读phone.actionable，或调用companion_phone查看；
true时调用已安装的social-reading插件plan，传life_intent=request.id。运行时固定
job_id=life-phone:<id>，认领后不再重复执行。原2h阅读任务的社交平台分支也只消费同一
意图，不再独立再抽一次；原图书/知识阅读规则及任务ID/节奏继续保留。

```json
{"op":"plugin_call","scope":"owner-private","plugin":"social-reading","action":"plan","life_intent":"真实request.id"}
```

浏览器只读已启用平台与已授权验证来源。当前贴吧适配已实现，B站/抖音仍planned_not_enabled。
以后实现视频适配时消费同一个手机意图及统一observation契约，不新增平行随机循环。
plan返回awaiting_sources/awaiting_verification/paused等会如实登记unavailable；busy不伪造
失败。observe成功才标read并关联真实document/source_event，阅读反思与情绪走原协议。
验证白屏标blocked，不产生虚构内容。超时未确认则会话结束标expired，不反复换ID重试。
手机日常完成只概括真实结果，具体看到了什么以独立真实观察为准；不先随机编好帖子剧情。

生命周期、真实阅读、情绪和成长分开：拿手机的意图/放下手机可以是虚拟日常；帖子与视频
观察必须真实；不把生活启动或同一篇重复观察当两次人格学习。不加额外模型或浏览器。
用户此轮明确要求手动阅读仍可走原manual入口，不受自主活动40/60抽签限制。
