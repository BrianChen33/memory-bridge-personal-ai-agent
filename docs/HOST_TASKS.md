# 宿主任务与可选渠道

`state/scheduler-blueprint.json`是默认停用的蓝图，不是Muse/Dot通用导入API。使用目标正式工具注册并读回实际ID、时区、频率、启用状态、目的地；不把旧任务整批重新启动。

| 职责 | 建议节奏 | 真实动作 |
|---|---|---|
| 生活/情绪 | 15m或廉价tick | companion_tick→pending claim→模型v2→life_assess→share claim→真实发送→settle |
| 新闻/邮件兴趣观察 | 30m | 真实来源、兴趣与日期、去重；有价值才分享 |
| 自主阅读/摘要 | 2h | 真实阅读claim/commit；capture article→observe；summary_work→commit→ack；后台向量索引 |
| 维护 | 每日 | 跳过繁忙消息队列；按scope合并候选、冲突与derive；people_sync |
| 每日总结 | 用户选择，如23:30 | 真实写日记→导出完整native定义→summary_done |
| 私库备份 | 紧接总结，或23:35补偿 | 只有summary_done存在才调用vault发布；验证远端commit |
| 公共梗知识同步 | 每周日07:40，一周一次 | meme-sync --mode full；匿名GET、持久进度、静默；私人解释不覆盖，不建立每日任务 |
| 提醒对账 | 5m | 对账真实runonce与账本，不能替代准点路径 |

01:00–07:00 Asia/Shanghai默认后台允许、主动分享暂停；用户主动来聊照常回复。无每日分享次数上限。备份可作为静默数据任务运行。失败记录并日间报告，不冒充已发消息。

## 生活调用

`companion_pending`带claim=true返回待评估事件与context；对每条调用`companion_life_assess {id,assessment}`，可share=true。`companion_share`先claim，实际发送后settle accepted/failed/unknown。静默时段不认领分享；unknown不自动重复发送。

## 人物绑定

`companion_bind {host_paths:{people_json:"真实名册路径",people_dir:"真实人物目录"},person_map:{"某页.md":"可信person_id"}}`由本机管理者调用。公开包默认只读STATE/native下的空目录，不擅自扫描home。相同姓名不能证明同人，旧数值不能赋予新权限。

## QQ/微信选择与适配

先问是否需要。若需要，再由用户提供/授权机器人或原生连接器，读取官方文档和真实schema。核对可信sender、group/私聊scope、稳定消息ID/时间、签名/轮询超时、回复窗口、主动限制、图片上传、重试去重与回执。

不打包任何旧账号密钥、回调域名、群ID、主人的openid、私有连接器地址或登录状态。桥接鉴权与人设分开。默认关闭；没有接口则明确未实现，不以提示词或假API代替。

裸@：只允许归一化层根据真实mention标识派生metadata_only=true/content_type=mention_only，正文不伪造；普通无负载空白直接安全归档，媒体消息另行处理。单条异常隔离，不能卡死整条队列。

可选表情策略操作为`op:expression`，source_event来自已完成有效模型评估的真实事件。配置源STATE/expression-policy.json供主bot和全部渠道读取；改策略不逐渠道写多份。

当前词表统一从companion_schema/emotion_catalog.py导出：v2、48标签。任务不得继续提交旧信封；新评估返回reaction供当前回复参考。原生主聊没有强制final钩子时如实报告，不能用轻量hook伪装全量消息观察。

梗API契约、配置/学习指令与预算见HUMOR.md。阅读任务可在真实article源事件上学习机制/联想，不能把自己的摘要冒充外部刺激；首次观察不自动成为确定理解。宿主注册新增任务时先查同名避免重复，用实际工具读回时区/周期/enabled/delivery。蓝图本身仍不等于已启用。
