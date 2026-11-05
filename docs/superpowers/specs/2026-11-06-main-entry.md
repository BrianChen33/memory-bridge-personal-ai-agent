# 主聊正式入口

用户要求在完成人格与生活更新后，阅读Muse主聊关于“不走正式入口”的三个方案，评估并直接
实施最佳方案。已实读原建议并核对原生schema：没有pre_send/native final拦截，chat.send_message
是给agent投递指令而非文本发送；chat.read_messages只能宿主调用，其实际返回为chat_id/page/
turns[id,items[role,content,seq,occurred_at_ms]]，字符串content已观察，其余不猜。

选用统一两阶段入口与真实本地状态校验、既有任务只读抽样补漏、阅读文档闭环。详见MAIN_ENTRY。
不增加模型，不在浏览时绕开正常输入，不伪造强平台钩子、真实主人事件或送达。旧finalize/finish
API保留兼容；新主聊采用context/commit。一次针对新增边界的隔离验收，不再重复完整已通过套件。
发布并核验公共版本/私库锁，再部署真实脚本和任务、短全局指针；不发送合成真人测试消息。
