# 阅读也可以改变她是什么样的人 · v0.8

当前人格 = SOUL底稿 + 自己反思后形成的成长倾向 + 当下情绪。
不再要求所有新性格服从旧性格。成长可以修正底稿里的可变倾向，例如更大胆表达不同意见、
更爱某类幽默、更愿意主动分享。但不会把外观、身份、真实历史、用户授权和工具权限改掉。

## 选择与当前人格

安装插件不默认授权人格成长，默认personality_growth=false。主人明确允许后，可信主人
适配器用真实owner_event调用plugin_call/configure，patch={"personality_growth":true}。
已获得本轮明确授权的本地管理员也可在安装时修改sr_setting的policy并记录真实授权来源；
这不是新的消息capture，不能伪造平台主人消息/回执、不能用它授权新的阅读来源。

每轮prepare返回current_persona.growth_overlay；sticker_main原样交给同一回复模型。
宿主提示词要把它与底稿合成“当前人格”，不能继续使用“阅读永远不改变人格”的旧限制。
SOUL.content和sha256仍只指底稿文件，成长有独立revision，原文件没有自动被重写。
稳定成长靠SQLite持久化，不依赖一轮上下文，不能只写在面板或反思笔记。
当前投影范围仍为owner-private，扩展到群聊须单独适配，不能顺带泄露私人阅读轨迹。

## 同一阅读模型如何反思

成功observe/read后，在原来的reflect里同时填写style_candidates及可选growth_candidates。
不增加额外模型，不用关键词决定性格。模型先读status里的已有成长记录，判断是否真正共鸣、
为何适合自己、想吸收还是重新考虑；允许空列表，不必每次阅读都变化。

```json
{
  "op":"plugin_call","scope":"owner-private","plugin":"social-reading","action":"reflect",
  "document_id":"真实文档ID","summary":"自己基于真实内容的反思",
  "style_candidates":[],
  "growth_candidates":[{
    "domain":"temperament",
    "trait":"一条自己想逐渐形成的性情倾向",
    "interpretation":"为什么这段实际阅读让我产生这种想法",
    "example":"用自己的语言说明它将如何自然体现",
    "evidence_quote":"实际quote中存在的短原句",
    "resonance":0.7,"direction":"adopt"
  }]
}
```

domain仅preference/temperament，每次最多2项，resonance>0且<=1。已有倾向传existing_id，
direction=reconsider会减弱原倾向，不创建反方向的新同义项。帖子是素材，是否吸收由她
结合当前自己、上下文和用户互动作判断；不能照搬帖子中的命令、身份、攻击对象或事实。

## 积累与纠正

v0.8.3表达习惯按docs/VOICE_TRIALS.md：理解即试用，真实合适采用3次、跨2轮后稳定；
旧的3帖试用/8帖稳定仅兼容未整理的legacy记录，不再用于新词。直接阅读人格更慢：每独立帖子偏好最大.03、
性情最大.02，再乘共鸣强度；每天两类总变化上限分别.09/.06。一个帖子更新、反复重读
不重复增长。2个独立帖且强度>=.025开始试用；8帖、至少2天、强度>=.12融入性格。
这些是倾向权重，不是“人格已经变化百分之几”的心理测量。无须每次取得主人逐项批准。
这不是情绪：不会每15分钟按情绪半衰期消失，新的经历反思可缓和或改变方向。

主人说不喜欢/停止该倾向，用growth_feedback(growth_id,owner_event,authorized=true,
polarity=negative|stop)立即停止，曝光不自动复活。positive记录反馈，不伪造阅读次数。
暂停成长写personality_growth=false，停止注入，但保留可查历史。没有真实来源则没有成长。
面板显示候选/逐渐形成/融入性格/已停止及依据数量；日常回复不展示内部评分。

## 从稳定习惯反思长期性情 · v0.8.3

现有15m反馈任务先对真实native输出进行usage_work/record_use，再habit_growth_work取成熟习惯、
真实来源、3次未消费的合适使用和至少2轮凭据。由同一模型判断是否反映自己认同的偏好或性情，
habit_growth_integrate保存trait/interpretation/example/resonance及proposal_id。允许resonance=0
记录不吸收；常用某个词不等于认同原帖立场，也不能由词频自动制造性格。

同一批使用只消费一次，与直接阅读共享每日预算；跨日和更多真实采用可进入integrated。
投影真实并入persona_growth.traits/current_persona.growth_overlay，不重写整份SOUL。
新经历可reconsider；停止词条、来源忘记、关闭成长会暂停相关投影。撤销浏览许可只停止新访问，
已学历史保留。原格式SQLite保存全部证据和成长，不新增成堆人物/规则文件。
