# 术语：个人 AI 智能体，而不是只说 Personal Bot

核对日期：2026-11-03。这里指 Meta 的 Muse 和 OpenAI 的 dot，不是其他同名产品。

## 推荐名称

**个人 AI 智能体（Personal AI Agent）**是主名称。需要强调持续在线的形态时，本项目用**常驻型个人 AI 智能体（Always-on Personal AI Agent）**，并另外说明它拥有持久的云端计算环境。

“常驻型个人 AI 智能体”是已有用语的组合描述，本文不把它宣称为各厂商共同发布的正式标准分类。“有云端电脑”是一种部署形态，不是所有个人 AI 智能体都必须满足的定义条件。

## 本项目的工作定义

面向特定用户长期服务，能够在持续保留工作状态的计算环境中使用工具、跨会话推进任务，并在授权范围内主动反馈结果的 AI 智能体。Muse 和 dot 所代表的云端形态还拥有自己的云端电脑、文件和浏览器，因此用户关闭本地设备后，部分云端工作仍能继续。

本项目为此类智能体添加可部署的外置记忆与运行流程；不替代基础模型，也不是厂商内部记忆 API。

## 官方用语依据

- Meta 的 [Muse 发布介绍](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/) 使用 **personal AI agent**，说明 Muse 在专用虚拟机与浏览器中工作，能够在用户关闭应用后继续任务。
- OpenAI 的 [Meet dots](https://learn.chatgpt.com/docs/dots) 使用 **always-on agent**，说明 dot 有自己的云端电脑与浏览器，可在对话之间持续推进工作。
- OpenAI 的 [Computers and apps](https://learn.chatgpt.com/docs/dots/computers-and-apps) 说明其云端电脑保留文件、软件和浏览器会话，连接用户本地电脑是另一项权限。

这些说明支持以上分类与定义，但不能证明每种产品都开放相同的文件、命令或定时 API；部署时仍须逐项核对真实工具。

## 其他常见词分别强调什么

| 术语 | 强调的方面 | 为什么不是本项目的主名称 |
|---|---|---|
| AI assistant | 助手角色 | 也包括仅处理当前请求的产品，范围更广 |
| Computer-use agent | 操作电脑/界面的能力 | 不一定有长期个人服务关系或持续状态 |
| Cloud agent | 云端运行 | 也可能是临时编码/工作流任务，不一定是个人智能体 |
| Autonomous agent | 任务中的自主程度 | 不表示无限权限或无需用户判断，也不特指持久云端电脑 |
| Personal Bot | 通俗称呼 | 容易与普通聊天机器人混淆，可作昵称，但分类采用 Personal AI Agent 更明确 |

Python 包名 `personal_bot` 为兼容的技术入口，不据此另造行业分类。将来新增平台时，按能力适配，不仅按产品名字判断。
