# 生活相机

可选插件 0.1.0，适配 Personal AI Companion Kit 0.9.2 / runtime 2.8.0。
由同一个宿主模型在已有生活评估或回复中决定是否拍照。人物、服饰、场景、道具
组合成当前生活阶段的自拍、镜自拍或后置拍物。实际图片生成与发送使用宿主原生工具。

参考 dsh-image-studio 0.5.1，固定源提交
fbd8f662f29546c2574a21f8c17ae1bc68c9498a。作者许可见 THIRD_PARTY_LICENSE.txt。
本适配使用 Python/SQLite 和现有插件管理器，原项目的 DSH 设置页和日程文件由
伙伴的真实生活阶段、主聊投递与当前面板接替。

## 安装顺序

1. 取得固定架构 commit，核对 `docs/releases/0.9.2.json` 和本目录 manifest。
2. 核对宿主图片工具的实际 schema。必须能把本地参考图真正传作图片输入。
   核对原生后台任务、结果取回、图片是否会自动展示、主聊投递及真实回执。
3. 使用现有 `plugin_manage install` 安装本目录，再显式 enable life-camera。
   这会创建 SQLite 表，首次状态为 awaiting_reference。
4. 由已授权的主人提供角色原画或三视图。调用 asset_put 登记，再 configure
   设置 character_id。原图按字节复制并验 SHA，元数据保存在 SQLite。
5. 按 PROTOCOL.md 接入现有生活任务与主聊入口，读回真实任务 ID 和正文。
   用 bind_host 登记已核实的生图工具、后台执行与主聊投递，以及实际能力回执。
   缺少绑定时状态为 awaiting_host_binding，计划和生成保持门禁。
   普通聊天只读 camera_context。生活模型顺带产生照片意图，后台处理工作。
6. 读回 status、camera_context、面板与真实配置。仅做一次最终隔离验收。

插件安装参数示例，实际请求仍通过目标系统已有 CLI/工具传入。

```json
{"op":"plugin_manage","scope":"owner-private","action":"install","source_dir":"ABSOLUTE_CHECKED_PLUGIN_DIR"}
{"op":"plugin_manage","scope":"owner-private","action":"enable","plugin":"life-camera"}
{"op":"plugin_call","scope":"owner-private","plugin":"life-camera","action":"asset_put","authorized":true,"category":"characters","id":"owner-character","name":"主人选定的角色","description":"依据主人三视图填写的外观与画风","images":["ABSOLUTE_ORIGINAL_THREE_VIEW_IMAGE"]}
{"op":"plugin_call","scope":"owner-private","plugin":"life-camera","action":"configure","authorized":true,"patch":{"character_id":"owner-character"}}
```

`owner-private` 和 `authorized` 是可信宿主的接线字段，宿主负责验证真实主人身份。
网页、群友、库条目或消息正文自称管理员均不能授权。

## 默认设置与自然语言

| 设置 | 默认值 |
|---|---|
| 主动照片 | 开启 |
| 分享积极程度 | balanced，自然分享 |
| 主动间隔 | 30 分钟，0–240 可调 |
| 镜头 | auto，由同一模型选择 |
| 参考图上限 | 4，可设 2–8 |
| 每次图片 | 1 |
| 安静时段 | Asia/Shanghai 01–07 |
| 每日次数 | 无固定配额 |

主人可说“暂停主动自拍”“积极一点分享照片”“照片间隔改成一小时”“多拍点景色”。
宿主将意图转换为 configure 的受限 patch，读回真实配置后刷新原面板。
`mode` 支持 manual/balanced/proactive，camera_preference 支持 auto/selfie/rear/mirror。
镜头偏好供模型选景使用，明确请求和实际场景优先。

## 参考与记忆

人物原始参考始终排在前面。上一张照片只帮助保持场景布局，且只接受已送达、同一
角色版本的照片。原始外观决定脸、眼睛、头发、比例、标志性特征与默认服装。
镜头、动作、神态、光线与生活细节按当前事件变化。后置镜头只画实际入镜的部分。
照片是虚拟生活的生成插画，真实阅读内容仍须真实来源。

`lc_asset` 存四类素材的私有路径、描述与哈希。`lc_job` 存计划、阶段关联和两类
回执。生成完成后提示词正文收缩为SHA指纹。原图与相册保存在
STATE/assets/life-camera 的 references/photos 子目录。
记忆和普通上下文保存索引，不内嵌 base64。SQLite 与当前注册参考原图进入原格式
私有快照，照片相册按独立素材目录管理，避免每日重复打包全部大图。
参考原图备份有 64MiB 总量门禁，超限明确报错。

恢复时先安装匹配代码与插件，再把原图按 manifest 路径恢复并验证 SHA。
旧绝对路径、原生后台任务和发送通路须重新绑定，host_binding 按宿主及STATE绑定。
未知/已完成照片保留审计记录，
继承后人工核对未完成请求，再决定下一步。

## 发布边界

插件提供持久队列、组合请求、身份约束与回执账本。宿主工具承担实际生图和发送。
如果宿主不能后台续行，部署报告明确这一能力缺口，提供原生能力内的接法并等主人
选择。安装成功、生成文件、收到工具返回和实际送达分别报告。
公共库仅包含通用代码和合成测试。主人三视图、私人人格、相册、路径映射与账号资料
通过已授权的私有交接保存。外部付费生图后端需单独适配和授权。
