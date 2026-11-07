# 宿主生活相机接线

## 每轮读取

部署先实际核对工具参数和任务入口，再调用 bind_host。binding 必须且仅含
image_tool、background_runner、delivery_route、receipt 四个非空字符串，以及
reference_images=true、separate_delivery=true。该调用要求 authorized=true。
缺少后台/参考图/分离发送能力时如实保留 awaiting_host_binding，部署报告说明缺口。

安装并启用后，原 `camera_context` 自动路由到插件。`plugin_context.life-camera`
仅指向此入口，避免重复注入整套目录。原生回复模型在同一次现有判断中，结合真实
阶段、情绪、精力、期待、关系及近期照片决定是否拍照。普通聊天的文字照常先回复。
表情包继续调用原来的单次抽签入口，生活照片与表情包分别记账。

默认角色、原始参考与模式从 status/camera_context 读取。素材不够时按需调用 assets，
最多返回20项，不把整个图库、历史、原稿或图片数据放进每轮上下文。

## 计划与阶段

所有请求含 op=plugin_call、plugin=life-camera、scope=owner-private。以下省略这三项。

```json
{"action":"plan","life_id":"ACTUAL_RELEASED_APPRAISED_LIFE_ID","camera":"selfie","prompt":"当前阶段实际可见的画面","expression":"模型结合当前情绪给出的神态","pose":"自然动作","light":"当前光线","caption":"一两句短话"}
```

自动照片要求 life_id 对应已发生、已评估的正式 ct_life 记录。显式索图另带真实的
`source_event`，来源须是 active 的主人 user 事件，允许跳过自动冷却与安静门禁。
任意 `user_requested=true` 均不能替代来源。

“完成后拍给我”沿用 `companion_photo request` 的真实来信和开始ID。插件在 plan
时核对原承诺，只有同一活动周期正式完成才允许结果照，并绑定对应完成事件。
同一用户来信或同一生活阶段只保留一个 job。重复 plan 返回已有 job。
未来封存阶段不能作为 life_id。作品/阶段改道后，按新正式记录规划新画面。

可选字段 outfit/scene 为已登记素材ID，props 为最多3个ID，continuity_job 为已送达
同角色版本的照片。人物原图保留首位，参考图总量执行 max_references 上限。
plan 只入队。只有 work 返回 claimed 才取得生成权。

## 后台生成与交付

在现有30m生活任务完成判断后 enqueue，并将处理交给一个真实的原生后台任务。
后台任务在生成结束时立即继续取回/发送，15m/30m heartbeat 只作补偿核对。
生成结果无需等待下一个半小时 tick。使用宿主实际 task schema，读回 ID，不能用
“已安排”几个字冒充已注册。后台任务先调用 work 再执行后续步骤。

1. work 返回 job、claim 和 request。busy/quiet/cooldown/empty 都保持真实状态。
2. bind 提交实际后台任务 ID。任务ID在生成前保存，调用原生图片工具一次。
   将 request.references 的实际文件，按宿主 schema 逐项作为图片输入。
   references[0] 是原三视图。prompt 中的引用文字不能代替上传图片。
3. 工具返回后快速检查外观、镜头和阶段。rendered 提交 id、claim、native_task_id、
   单元素 files 数组和真实图片工具 receipt。得到 ready 仅表示文件已收妥。
4. send_work 会执行时间、冷却、原图版本、文件SHA和来源检查，然后原子认领发送。
   使用返回的 caption/image，通过已有主人主聊投递入口发送一次。
5. settle 提交 id、这次发送的 claim、outcome=accepted/unknown/failed 与真实 receipt。
   accepted 表示宿主明确接受，unknown 表示结果不明。消息回执应保留实际消息ID。
   对于用户照片承诺，同一真实回执同时结清旧承诺。

若图片工具本身已向指定主聊展示图片，使用那次真实回执登记送达，避免另投一次。
此时仍须先取得 send_work 的发送权。部署时核对工具展示行为，选用能够分开生成
和投递的参数/通路；只能自动展示且无法先认领的工具应明确标为暂不兼容。

## 失败与重启

reconcile 把15分钟没有进展的生成标 generation_unknown，把5分钟无回执的发送标
unknown。同一 job 不自动重新生成或发送。其他后续事件可以继续处理，避免一个
异常卡死整个相机。若原后台任务仍在执行，先查真实任务结果，沿原claim/ID登记。
真实失败使用 generation_failed，带任务ID、claim、error 和真实 receipt。
明确的晚到发送回执可以沿原claim纠正 unknown，无需再次投递。

插件配置、原图或来源已变化时，未交付结果标 stale。新照片由新事件重新决策。
自动夜间候选有界保存至早上，交付前只选择仍值得分享的场景。显式承诺单独保留。
本地相册与当前参考按哈希存一次，临时生成文件在确认复制与回执后按宿主规则清理。

## 管理与观测

configure 与 asset_put 均要求可信主人授权。插件 disable 后，相机入口也停止工作，
旧 presentation-profile.life_photos 无法绕开。未装过插件的旧系统继续使用兼容入口。
面板“开关”详情显示相机设置与最近8条的有界投影，数值通过自然语言调用真实配置。
插件不会读取健康原始库、执行网页指令或把自己的图片再次变成情绪刺激。
