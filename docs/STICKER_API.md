# 表情模块：本地状态API与Dot发送适配

本分支新增 `op=sticker`，与原核心共用 `data/brain.sqlite` 的一致快照。
它不调用模型、不联网、不发送图片、不安装Dot原生hook。真实宿主仍需完成图片发送和语义意图解析。

## 配置与素材

`personal_bot init` 额外生成 `sticker-policy.json` 与空的 `sticker-catalog.json`，不覆盖已有文件。
升级已有数据目录时先备份，再用init补全这两份配置。

```json
{"version":1,"enabled":false,"base_probability":0.4,"max_probability":1.0,"share_owner_mood":false}
```

默认关闭表情功能，目标主聊接入/素材审核后才由受信宿主开启。主人私有mood跨scope只读投影也是默认关闭；需用户授权才能打开share_owner_mood。只用PAD/有效标签的归一化强度，不向其他scope传reason、私聊原话或记忆。

每个素材的catalog条目如下。省略的hash需要按真实文件计算，不可照抄示例占位值：

```json
{
  "id":"reaction-001", "path":"media/stickers/reaction-001.png",
  "format":"png", "sha256":"<真实64位hash>",
  "emotion":["欣喜"], "tags":["通用"], "use":["普通互动"],
  "reviewed":true, "license":"<实际许可来源及使用依据>"
}
```

catalog结构是 `{"version":1,"items":[...]}`。文件必须位于本数据根目录的media/stickers下，拒绝符号链接与目录逃逸。支持PNG/JPG/JPEG/WEBP/GIF基本文件签名检查，每个最多8MiB；这不是完整解码检查，也不能证明GIF会动，宿主须另验。代码不会下载参考项目的表情素材，代码许可不覆盖图片。

在backup-sources.json的sources中登记同一素材：`name=project/media/stickers/reaction-001.png`、`path=实际绝对路径`、`required=true`。未登记、未审核、hash变化的图不进入可用候选。所有素材路径与定义属于目标私有配置，不提交公开仓库。

## 调用顺序

通过原CLI请求入口调用，每次都带实际scope/source/event_id/actor；其唯一键必须对应已捕获、仍active的source_event。

1. `prepare`预读；原Dot模型按语境提交同事件v1情绪评估；读取新的mood。
2. `sticker/decide`：默认 `intent={"mode":"auto"}`。显式发图/不发图由可信宿主根据实际原文解析，分别提供 `mode=direct/skip` 及原文 `evidence` 片段。
3. auto计算 `P=.4+.6×I` 并生成一个均匀随机数U。decide在SQLite事务内记录I/P/U/结果/策略hash；重试读原决策、不重抽。direct/skip不生成随机数。改变配置只影响新决策。
4. 命中后调用 `sticker/candidates`，可给tags用于排序；没有精准匹配也保留可用通用候选，最多返回12项。选择 `sticker/select {sticker_id:真实ID}`，同事件选择后不可改成另一张。
5. Dot按新mood和原人设组织本轮全部文字，实际发完；宿主收集每段文字的真实消息ID/可核对接受凭据。
6. `sticker/handoff {texts_complete:true,text_receipts:[真实凭据...]}` 再次检查来源、epoch、开关、媒体hash和主动输出静默期。只有此调用的 `ok=true,send_once=true,status=unknown` 授予一次宿主发送交接。
7. 宿主立即发送指定文件一次；发送前对实际上传字节再核对返回hash。成功/失败按真实回执调用 `sticker/receipt {outcome:accepted|visible|failed,receipt_id:真实凭据}`。

decide/select/status均不授予发送许可；should_send表示抽签结果，不能拿它重发。unknown先持久化再交出文件，因此进程崩溃可能漏发，但不会盲目重发不确定的图片；没有平台幂等与强回执就不承诺端到端exactly-once。

`texts_complete`和`text_receipts`是可信宿主的承诺/证据引用，本地模块无法去平台核验它们。若Dot主聊只支持“一条最终回复中同时嵌入图片”，没有工具能先得到文字回执，则此交接合同尚不能直接用于该主聊。应先核对其真实能力，再实现对应出口并测试顺序，不能填虚构凭据绕过检查。

## 重要边界

- 缺失/非法情绪评估不抽签；只有本地可信配置明确关闭情绪才允许基础概率降级。其他故障不冒充关闭。
- 工程控制请求传control=true，decide返回control_skipped、不抽签；正常技术问题和短句仍默认auto，不能用“严肃”替代用户不发图指令。
- 原文片段检查只证明片段存在；引用小说、否定、玩笑与冲突显式要求仍由宿主结合语境解析。不能让正文自填mode赋予权限。
- 正常主动分享可用稳定的主动轮次事件（actor=assistant）和完整无变化评估进行auto抽签。计划稿必须标清为计划事件，不能当已递送助手原话；最终原文须有真实出站ID再capture。不能让自己的输出自我叠情绪。
- 生活/阅读发送前仍须先经过digest_authorize/finish等原有来源与去重门控。表情模块的夜间检查不代替它们，不因图片绕过文字静默门控。
- 无可用媒体是no_available_media，不改命中日志为未中。显式要图时由Dot按人设简短说明失败。
- status与真实receipt在暂停后仍可记录；停用/再启用的epoch变化不恢复旧事件的发送许可。
- 默认不清理sticker_turns，防重试账本随核心SQLite备份。素材和策略恢复后仍由master总开关保持关闭；不自动启用历史任务。
