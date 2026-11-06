# 固定主聊入口 · v0.8.5

目标是减少工具编排，不跳过人格、记忆、同模型full48评估或每轮一次表情决策。
Muse没有公开native-final/after_reply拦截，下面是宿主明确调用的固定驱动，不是新平台API。

安装时读一次本文、MAIN_ENTRY.md、实际媒体工具schema，设置真实主聊短入口指针。
每轮不重读整份协议，不新写build_commit.py，不重复检索，不为短句分别评估或抽签。

```sh
node /actual/stickers/src/reply_driver.mjs --root /actual/workspace --chat-id ACTUAL_CHAT < request.json
```

1. 宿主真实chat.read_messages取源，传`{phase:context,native_response:真实返回}`。
   允许MAIN_ENTRY.md规定的无损user投影。固定请求文件可以覆盖，不能手抄/截断原文。
   返回ticket、context和compact48-v1的emotion_template；保留原48词表，只填写实际变化。票据仅在私有目录保存选中turn全部真实user项。
2. 同一个回复模型结合当前人格/语境判断自身感受；emotion_deltas只报实际变化，未报为0、可为空，传
   `{phase:commit,ticket:刚才值,emotion_assessment:按返回格式填好的完整信封}`。保留context供组文。
   可以同次传media_query/media_emotion作为宽松选图偏好。没有独立情绪模型或第二次prepare。
3. `ready_to_send=true`后直接回复。commit抽中时自动读取本地索引，从宽松前10个有效候选中
   随机选一个，校验缓存并返回`media.path`。同一次native final先全部短句，最后附真实本地图片。
   选图失败不重抽，不下载阻塞正文，不把抽中说成没中；明确索图缺素材则如实处理。
4. gate/选图不等于发送。真实发送后若宿主有回执，调用
   `{phase:finish,ticket,receipt:真实原生尝试/结果标识,outcome:accepted|failed|unknown|text_only,text_finished:true}`。
   没有after_reply时，不得提前finish伪造已发：保持unconfirmed，由后续有真实证据的宿主反馈结算。
   unknown不会自动重发。后续重放选图复用同一个asset，不重新随机选一张。

本地素材约定：`WORKSPACE/stickers/meta/nekowhale.json`含stickers数组，id、hash(12位SHA1)、
emotion、text、tags/use/desc；`assets/<hash>.gif`须魔数及hash相符。代码不捆绑第三方素材。
`recently_sent.json`兼容既有渠道的`{asset_id:epoch_ms}`一小时避重；主聊另保存一小时选图
预留`recently_reserved.json`，并向既有共享避重账本写保守占位，让旧渠道也避开；占位不是
送达证明，decision仍not_handed_off。真实finish再更新实际尝试时间；失败可按确切占位释放。
本版不改私人QQ/微信发送器，也不承诺旧发送器之间的原子并发预留。重放不延长实际尝试时间。

长工具工作后可在commit传fresh native_response；新来信会拒绝旧target。票据绑定原文SHA、
时间、seq、主聊及JS/Python核心文件指纹，24h失效；版本变化重新context，不能沿用旧票据。
主聊拿到主人阅读请求：先正常context/full48/commit，queue_enqueue后简短回应已登记；后台
消费队列。需要近期后台启动可使用READING_QUEUE.md的真实未来handoff，不能在前台读十分钟。
普通闲聊不等待其他阅读或全库pending清空。记忆写入/维护/面板不应夹在commit与正文之间。

计时只记录200条无正文元数据到reply-rounds/timings.json，并投影reply-driver-health.json。
`local_ms/core_ms`是本地调用时间；`source_elapsed_ms`包含模型、工具、平台排队和时间戳差，
不是模型耗时。stats只读。尚无平台分段遥测时，不能声称测到了排队或承诺固定秒数。

隐私：reply-rounds含原始来信，只留私有环境，不进公共库。迁移不导入旧票据重放消息。

v0.8.5只精简模型填写；本地验证前扩展为完整48项，旧full48输入仍严格校验。
按MODEL_EMOTION.md先看个人意义，不把执行请求自动当开心。正文用当前reaction+残留mood，
没有额外前置自省或新模型调用。不要把旧“必须手写48个零”的规则再注入新driver主聊。
