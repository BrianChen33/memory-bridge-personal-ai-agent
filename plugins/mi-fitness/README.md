# 小米睡眠与运动 · 可选插件0.1.0

只读取本人睡眠、步数、活动量和锻炼摘要。默认不安装，不注册上游通用
MCP、不开放原始请求、独立心率/血氧/压力/体重/人物资料/亲友/GPS。
本插件使用MIT项目[Jenwein/mifit](https://github.com/Jenwein/mifit)0.4.0；
它是非官方云端协议，数据必须先由手机App同步，缺数据不等于0。

核心仍用Python3.10+，联网worker单独需要Python3.12+。SDK只在后台sync
进程导入；正常主聊使用既有plugin_context钩子读不足16KB的本地投影，
不新增模型、逐消息请求或定时器。只有owner-private返回数据。

## 安装与本机扫码交接

1. 得到用户明确授权，并确认账号地区、读取类别和云同步。只配置已经
   授权的类别。本版固定四种；想缩小范围时应修改受限适配器而非提示词。
   另说明真实数据流：主聊中实际说出的健康摘要会由既有反馈/聊天记忆收录，
   如已开启私有GitHub记忆备份，也会随brain备份。须单独取得用户对这一
   范围和目的地的同意；默认不输出健康context/care/history。未同意时只能
   静默采集或停用；不能宣称已实现主聊健康全文的备份排除。
2. 宿主选择brain/工作区/所有备份源之外的私有目录，例如
   `~/.config/muse-health-bridge`，权限700；令牌文件600。单独建`.venv`并
   `python -m pip install -r plugins/mi-fitness/requirements.txt`。
3. 宿主生成一次性RSA3072密钥，只给本机SPKI公钥、DER SHA256指纹和
   随机32位hex transfer_id。私钥不离开宿主。
4. 用户本机在受保护目录运行：

   ```text
   python local_login.py --public-key recipient.pem --transfer-id ID \
     --fingerprint SHA256 --output-dir PRIVATE_LOCAL_DIR
   ```

   用户亲自扫码确认；本机仅写二维码与收件人加密包，不写明文凭据。
   只把`muse-mi-fitness-session.sealed.json`密文附件交给宿主，不贴明文、
   不上传到任何GitHub；公钥指纹必须与宿主回执一致。
5. 宿主从实际附件工具取得密文路径，核文件SHA和收件人指纹，在worker
   环境执行（命令参数只有文件路径、公开指纹和transfer_id）：

   ```text
   python bridge.py --private-dir PRIVATE --scope owner-private import \
     --envelope SEALED_FILE --key ONE_TIME_PRIVATE_KEY \
     --transfer-id ID --fingerprint SHA256
   ```

   校验RSA-OAEP-SHA256、AES-GCM、收件人、用途和1小时交接有效期后，原子
   保存session.json，清除一次性私钥；只返回成功与许可类别，不打印令牌。
6. 固定commit核manifest文件SHA，按现有`plugin_manage install/enable`
   安装`mi-fitness`。`brain/mi-fitness.json`只保存私有目录和worker Python
   路径，不含凭据；路径必须位于brain之外。Windows宿主需把worker_python
   改成其`.venv/Scripts/python.exe`。读取类别固定，不提供扩权配置接口。

上游登录态包含小米账号续期凭据，**并非仅睡眠/运动的官方OAuth权限**。
本版限制由适配器和宿主权限共同实施，不能把它宣称为小米服务端强制
隔离。宿主不得绕过白名单调用SDK。若用户不接受账号续期凭据在宿主，
改用本地采集后只推送摘要的方案；不能偷偷扩大授权或关闭安全检查。

## 六层如何结合

- 输入：数据标为`Mi Fitness cloud; observed owner data`，保留日期、同步
  时间、单位和缺失值；真实身体观察与虚拟生活、梦境严格分开。
- 记忆：独立health.sqlite按天覆盖，保留90天；history最多31天，支持回顾
  睡眠与运动变化。不把原始缓存整库导入brain或日记。用户明确允许后，
  实际对话里的健康摘要按既有聊天记忆/反馈和私有GitHub备份处理。
- 情绪：同一个回复模型结合真实对话决定关切、认可或担心；不按数值
  自动改情绪，不把主人的精力当自己的精力，不重复评估缓存作新刺激。
- 生活：并入现有life30m任务，每小时最多一次sync，首次取最近7天、此后
  回补3天。第一次只建基线；新睡眠/锻炼才成为可选care候选，不因步数
  每次增长就催促。不新增独立健康heartbeat。
- 表达：按人设短句自然关心，例如注意到新运动可以问感受；查询时可按
  7天history回顾。自主分享走原主动消息/每轮贴纸入口；不把数值当诊断
  或把设备“压力”当用户心理状态。群聊不暴露主人健康记录。
- 反馈：每条care候选先claim，真实送达后settle；未发送用suppressed，
  不明用unknown且不自动重发。凌晨01–07只同步，不主动分享。

## 宿主接线（真实接口，禁止猜API）

通过已有`plugin_call`请求，`plugin="mi-fitness"`、`scope="owner-private"`：

| action | 用途 |
|---|---|
| `status` | 许可、版本与同步时间，无测量值 |
| `authorize_chat_summary_memory, authorized=true, allowed=bool` | 可信主人明确选择实际对话摘要是否进入既有私有记忆/备份；默认false |
| `sync` | 后台小时门禁内增量同步；不在普通回复前运行 |
| `context` | 本地精简投影，无联网 |
| `history, days=1..31` | 查询本地逐日记录，无联网 |
| `care_work` | 现有生活任务领取最多2条新观察；安静时段为空 |
| `care_settle, candidate, outcome, receipt` | delivered需真实回执；suppressed/unknown不重发 |

更新现有life30m任务正文而非复制新任务：先健康sync，再care_work，其余
原流程继续。候选是主人观察，不是机器人亲身生活；使用既有proactive
入口且`source_events=[]`，避免伪造ct_life或自刺激。原情绪15m任务不联网。
确认reply_driver既有context实际带plugin_context.mi-fitness，再由同一模型
按相关性使用；不改SOUL、不每轮重读本文或重新扫码。

## 保密与继承

session.json、health.sqlite、context.json、交接密文/二维码/私钥全部在
备份范围之外。实际主聊摘要只有在用户同意后才可沿用既有记忆/私库链路；
这与排除原始健康文件不同，不能承诺聊天全文也自动保密隔离。
新增manifest只含插件代码。继承只恢复插件版本/启用意愿
和路径配置，原始凭据与独立健康历史不继承；新Agent需重新授权，摘要
记忆意愿也须重新确认。已获授权并保存在旧聊天记忆中的摘要按其来源继承。
查询/测量也可能出现在宿主模型工具上下文，这是用户授权的分析用途，
不等于公开或进入通用记忆。自行检查宿主日志和备份实际覆盖范围。

需要退出时停用插件和现有任务内的健康分支，不改变其他任务；由用户在
小米账号安全中心撤销登录态。本插件不修改或删除小米云端健康数据。
