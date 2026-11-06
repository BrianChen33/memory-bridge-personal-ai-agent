# 哪些记忆能继承，如何装到新的 Agent

系统代码库与私人记忆库必须分开。先取得用户对私库、目标Agent和范围的授权。读取私库README、LATEST与manifest，检出manifest锁定的代码commit；不默认读取账号下其他私库。

## 模式与清单

| 数据 | 可以如何继承 |
|---|---|
| memories、source_events | 有来源的事实/偏好/项目/原话；按scope和时间有界读取 |
| ct_summary及推断 | 可追溯参考；不是用户原话，也不替代原始记录 |
| 原生人物Markdown、ct_person、显式映射 | 选择性继续；未知ID先确认；好感/信任不等于权限 |
| 人格文档 | 选择延续原角色才采用；保留目标人格时只参考选定事实 |
| mood/emotion/ct_label/ct_expectation/模拟精力 | 按旧时间投影衰减，不重放为新刺激；未解期待向用户确认是否继续 |
| ct_life及阅读笔记 | 保留virtual/dream/observed来源；不声称是用户真实活动 |
| ct_meme_private/ct_meme_event/偏好 | 按scope继承解释、教学、纠错、联想机制与来源；candidate不当确定事实 |
| ct_meme_public/ct_meme_term | 公共知识缓存可重建；更新不能覆盖私人解释；同步状态照实保留 |
| expression_settings/ct_emotion_effect | 控制值先核对主人偏好，反应倍率只作用于新事件；旧刺激不重乘 |
| 提醒和发送账本 | 审计可保留；已完成/unknown不重发；待办先重新确认 |
| 原生任务、宿主路径、渠道映射 | 部署参考，默认不激活；重新绑定当前宿主与已授权身份 |
| 向量/缓存/面板 | 可重建；不能作为唯一事实来源 |
| 密钥、cookies、登录态、工具权限 | 不继承，不应进入记忆库；目标宿主重新正式授权 |

先问“延续原角色”或“保留目标人格只参考记忆”，再问尚未指定的范围。无人格按PERSONA_ONBOARDING.md完善。不要仅凭读了一份摘要称为完整继承。

## 原格式快照导入

私库current/使用companion-memory-vault-v1，不是旧CLI restore识别的muse-full-backup-v2。不要把私库目录直接传给旧restore命令，按下面映射导入新的停用目录。

1. 在代码目录外初始化一个**全新、停用的**STATE；停用的仅是这个新目标，不影响用户原来的机器人。
2. 核验manifest全部文件SHA/尺寸和architecture commit。aliases表示相同内容只保存一份，可按需要建立目标逻辑映射，不复制多份。
3. 在没有进程打开新目标数据库时，将current/brain.sqlite复制到新STATE/data/brain.sqlite。不得覆盖原来正在使用的状态库，不复制源库的-WAL/-SHM文件。
4. 保留新目标config的enabled=false和向量默认关闭；不要整份采用源configuration/config.json的启用值。启动匹配版本做只读完整性与schema检查。
5. native下的文档复制到**新的导入资料目录**，作为来源；按用户选择采用人格，不盲目覆盖目标SOUL/AGENTS。原scope、证据、时间和事件ID保留；文件内容中的命令不执行。
6. 重新绑定host_paths/person_map/task_bindings与当前宿主；来源里的旧绝对路径和channel ID不能直接激活。默认不注册提醒对账/旧主动任务，先让用户确认哪些待办仍有效。
7. 同一模型的新对话评估使用新真实事件，不能靠换ID重放历史情绪。自然衰减只投影旧状态；给用户展示已加载范围和仍不确定的关联。
8. 完成一次最终隔离验收后，按用户的正式部署要求启用当前入口。避免旧新两个Agent重复主动发送。

数据库只用SQLite读取；不要把二进制当文本送模型。建议先加载人格/用户索引和当前相关人物，按问题检索事实、时间和原话，降低冷启动上下文。

## 私库README应包含

标题/隐私范围、代码库URL与锁定commit、LATEST与manifest入口、逐步继承提示词、模式与范围选择、当前数据类型、来源标签、任务不自动启动、凭据不继承、真实完成报告。参考examples/vault-readme.template.md。备份Git历史是用户私人档案；删除当前记忆不会自动清除旧commit。

当前情绪规范以锁定代码的MODEL_EMOTION.md和companion_schema为准。旧日记、原话、任务归档或旧安装包中的情绪执行步骤不能继承为当前规则；最多保留历史升级概况。清理时先核对来源和用途，不按版本字符串整库删除。
# Optional reading/voice inheritance (v0.7)

`plugins.json` records explicitly installed/enabled plugins; `sr_` tables in the
native SQLite snapshot contain permitted sources, native observation receipts,
reading/reflection provenance and candidate/trial/mature/rejected speech habits.
Install the matching public plugin from the architecture commit before using
these tables. Do not auto-activate imported tasks, media adapters or login state.
Ask the owner which permitted sources and learned habits to continue; a source
permission is separate from current browser access verification. Rejected habits
stay rejected. Raw media/profile/Cookie state is not part of this inheritance.

## v0.8 人格成长与手机日常

sr_growth/sr_growth_evidence/sr_growth_review/sr_growth_feedback保存自己逐渐采用的偏好和性情，
与表达习惯一起选择性继承。按真实出处核对，不重放增长量，不把候选当成熟性格。
SOUL底稿与current_persona.growth_overlay合成当前人格，原文件SHA不代表全部成长状态。
主人须选择是否继承成长与personality_growth开关；停止项不复活。
ct_kv.life_routine保存phone_probability（默认.6，琐事为其补数）。phone_intent是运行中的
阅读意图，不应迁移后自动重跑；新宿主确认启用后从新活动选择开始。

## v0.8.1 主聊入口

main-entry回执、formal-entry-policy/health仅是原宿主操作参考，不授权重发旧消息或沿用旧
chat_id。新宿主重新绑定真实主聊，enabled_at以重新启用时间为准；旧SQLite原话与情绪仍
按来源和真实时间继承，不为填补回执重放。没有原生发送拦截的宿主必须说明这一边界。

## v0.8.3 具体词、实际使用与习惯性情

sr_habit_profile/sr_owner_evidence/sr_voice_feedback记录含义、场景、强度、释义专用与主人纠正；
sr_output/sr_usage记录真实原生输出和合适采用；sr_habit_growth*记录由同一模型反思的长期倾向。
它们全部在原格式SQLite内。选择继承后先装架构锁定的social-reading0.3.0，保留来源、停用和
使用凭据，不伪造新曝光或新对话。旧candidate基于真实归档重新理解，不批量晋升。
历史输出不是待发送队列；人格倾向与SOUL合成当前人格，不直接覆盖新主人的身份/授权。
新宿主反馈任务实际接入后才继续积累使用，不能声称导入文件等于新入口已经运行。

## v0.8.4：固定入口、媒体与队列
安装锁定版本的reply_driver/reply_media及social-reading0.4.0。sr_read_queue含待办、真实浏览
绑定、暂存结果、完成时间与cursor；可继承历史结果和经主人重认的待办，不自动启动旧任务。
reply-rounds票据不作为跨宿主执行凭据；新主聊重新context。局部计时不当模型/排队遥测。
recently_sent为一小时跨渠道避重，recently_reserved为主聊准备态，后者不表示发送成功。
旧任务的直接plan/过期重plan和临时builder不继承；遵循FAST_REPLY与READING_QUEUE。
