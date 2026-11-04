# Muse / Dot 接入

使用README完整提示词与DEPLOY_FOR_BOT.md，不猜平台API。先查本环境正式文档/连接器schema，确认持久电脑、消息元数据、原生任务与媒体发送能力。技术调试放用户指定旁聊，普通用户保持人格。

主聊：prepare→当前模型v2→同事件prepare→新状态组文，转交companion/scene_context/persona_context。平台没有强制hook时以主bot规则接入并如实标注可能漏调用。

原生任务：按HOST_TASKS.md注册，读回真实ID/频率/启用与目的地。不要将提示词“已更新”当成服务或任务已重载；修改常驻桥接源码后按它原有监督方式重载，再读状态。

资料库：以本环境文档为准。参考Muse文档支持workspace/your_files文件作为Library构件，同路径编辑更新预览；System Files是文件系统窗口。未证实跨文件JSON API或秒级刷新，不能承诺在线实时。

GitHub：某些原生连接器只支持UTF-8文本，原始SQLite需要正式二进制发送能力或用户授权的仓库专用SSH方式。不能把私钥或广权限token贴进聊天，不能绕过平台认证规则。

QQ/微信：用户选择后才适配正式接口、可信scope、鉴权、回复窗口、图片与去重；公共包不含任何现成账号或登录态。初次人格缺失时先协助完成卡片，而非套用本项目作者的人设。
