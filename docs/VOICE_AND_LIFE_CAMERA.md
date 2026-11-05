# 当前人格、主动查梗与日常照片（v0.6.3）

长聊天中的旧示例、启动时注入的SOUL和L3用户画像，均不能代替当前人格。只改SOUL文件也不能解决主聊漏调用prepare。先修真实入口，再调整表达。

## 每轮同一入口

真人消息使用真实原生ID运行现有主聊适配器的`phase=context`，将`context.current_persona`、`expression_context`、`camera_context`与reaction交给同一个回复模型；同事件`commit`提交评估、做一次表情决策并校验回执（旧`finalize`仅兼容），发送后`finish`记录回执。调试按原control/skip规则，不伪造真人事件。

不得同时保留一份只prepare/capture的旧主聊说明和另一份context/finalize/finish说明。若宿主仅靠模型约定执行，明确这仍不是平台硬钩子。让当前主聊实际读取更新后的入口与SOUL；没有正式reload接口时不能声称已经调用它。

私有STATE可保存`presentation-profile.json`：

```json
{"persona_file":"/actual/private/SOUL.md","life_photos":true,"camera_guide":"/actual/private/LIFE_CAMERA.md","character_references":["/actual/private/character-front.png"]}
```

相对路径按STATE解析。只在宿主实际支持的工具中使用这些路径。每次prepare读取当下的短SOUL及SHA，不依赖召回缓存；最多2400字符，超长明确truncated。工具程序、权限、情绪schema和抽签协议放在唯一技术文档，SOUL留身份、偏好、关系和说话气质。`persona_context`仍是有来源的L3摘要，不是新SOUL。群聊/其他私聊仅在配置`public_persona_file`后接收单独的公开人格卡，避免把主人私人人格内容外传。

## 查梗是后台理解，玩梗是表达选择

`auto_memes`开启时，prepare已有本地候选预取；`expression_context.lookup`如实给attempted/source_event/candidate_count。没有prepare，就不能说该轮查过。遇到不熟悉的缩写、押韵短句或人名组合，候选不足时主动用`meme_search`查询简短关键词；查不到保留不确定，不先判定手滑。可靠的已学接法直接使用，不报告“记好了”、不解释笑点，不为了表示查过而硬塞梗。

串子程度是允许的力度，不是攻击配额。优先接当前一句的细节，允许反转、类比、回扣、自嘲和安静；不用模式宣言、固定称呼和长篇挖苦替代人格。默认1–3条完整短句，一句够了就停；必要解释照常展开。保留用户实际配置，不把人格气质比例写成程度或概率。

## 参考图、镜头和时间

1. 用用户选定的**机器人本人的表情原画**做风格/身份参考。可将现有GIF中的代表帧无改画地导出为PNG，保存来源与SHA。不可用人类用户的profile照片代替机器人；不能从“某种动物娘”几个词重新设计脸、耳朵和手。
2. “手机照片”指定构图、取景和生活感；画风仍跟参考图。参考是Q版插画时，不能因此切成真人摄影、3D或怪异仿真皮肤。像素等画风仅在用户选择时改变。
3. 后置POV：只描写镜头前的物件和入镜部位。拿手机的人不用整套人物外貌描述；无镜子、自拍或反射依据时，不把自己的脸画进后置画面。自拍锁定参考人物，镜自拍要说明真实镜面和手机位置。独居场景不凭空增加旁人或陪伴动物。
4. 提示词依次写：参考角色/风格、镜头、当前阶段的主体、可见部位、环境与少量意外、必要排除项。具体手部形态以该角色原画与用户说明为准。不要让不可见的头发/耳朵等抢走后置画面的主体。
5. 先读`camera_context.activity`的started_at/ends_at/elapsed与recent_milestones。已经进行一阵的事情不要说“刚准备”；started行保留原样，完成是另一个事件。用户在完成前索图时展示准备/进行中的场景；没有完成依据，不用成品图补写虚假结果。
   若真实时钟已到ends_at但尚未落完成记录，可通过已有companion_tick按真实时钟推进，再读当前阶段；不能直接改时间或口头宣称完成。
6. 有画面值得分享的新生活阶段可主动配图，无须等用户再次索要。并非每次微小数值衰减都要重新生图。虚拟经历、梦境和真实阅读内部来源分开；生成图不是现实相机证据。

可复用后置模板：

```text
Use the supplied character artwork as the style reference. A casual rear-camera
POV snapshot rendered in that same cute illustrated style. Main subject: [what
is actually present at this stage]. Only [visible body part, if any], with the
same drawing language as the reference. [Scene, lighting, one plausible detail].
The camera holder stays behind the camera. No invented companion or extra body.
```

用宿主真实图片参数附参考图，并遵守该工具正式要求的身份标签与输入顺序；文字里提到“参考图”不等于实际传入。固定身份标签容易误指人类用户时，另加明确角色说明，不能改用用户私人照片。

## 照片承诺闭环，不加定时器

用户说“出炉后拍给我”，在已经prepare得到真实source_event之后登记：

```json
{"op":"companion_photo","scope":"owner-private","action":"request","source_event":123,"activity_id":"ACTUAL_STARTED_LIFE_ID","camera":"rear","when":"completed"}
```

when还可为now，camera还可为selfie/mirror。请求存现有SQLite的ct_kv，同源同计划重试不重复。已有生活任务继续tick/评估，随后读取`companion_pending.camera_context.photo_requests`；只有ready才生成约定的结果照片。按activity_id与对应开始/完成周期匹配，不能用上一轮同名活动的完成记录履约。没有完成时不假装收到。

本轮完成分享的配图可以同时履行照片请求，使用同一真实回执，不再生成第二张。实际交付后用`companion_photo action=settle,source_event=123,outcome=accepted|unknown|failed`登记；accepted需宿主真实结果，unknown不自动重发。只生成文件不等于送达。自动分享照常遵守安静时段；用户主动索图照常回应。不为每张照片另建原生任务，不给闲聊人为加等待。

这些小型配置及请求随私库备份；参考图可以从已有合法素材重建，公共库不包含私人人格或图片。继承时先核对宿主图片能力和未完成请求，不重发旧unknown结果。

当前主聊完整取源与门禁以[MAIN_ENTRY.md](MAIN_ENTRY.md)为准；native final硬边界不能用技能提示掩盖。
