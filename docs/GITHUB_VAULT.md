# 每日原格式记忆 → GitHub 私有库

这与旧memory_bridge逐项授权文本交换是不同功能。只有用户明确要求整库私有备份时配置。本模块需要git、OpenSSH、出站HTTPS与仅指定私库可写的本地SSH deploy key；私钥留宿主，不进模型上下文或仓库。

## 数据与回执

`python -m personal_bot.vault`使用SQLite Online Backup API导出含WAL已提交状态的一致性`.sqlite`；复制backup-sources.json明确登记的原生人格/记忆/任务文档，按SHA去重并记录aliases；程序/模型/旧回退原件不每日重复复制，只锁定公开架构commit。`.env`、私钥、登录态、敏感凭据路径和明显token拒绝导出；不要把用户家目录当备份树。

`current/`固定路径更新，Git保存历史；LATEST指向当前完整清单。保留原格式，不把SQLite改成base64或摘要。每份快照包含bootstrap/daily类型；daily要求ct_kv中有真实daily_summary日期记录。

## 设置步骤

1. 用户指定或新建PRIVATE仓库，先写README继承提示词并初始化main。该库不能与公共架构库混用。
2. 若已有正式认证可提交原始二进制则复用。部分平台连接器只收UTF-8，不能把binary传入文本参数。需要SSH时按用户授权准备仓库专用keypair，私钥仅宿主，公钥登记仅本库可写deploy key；不复制别的电脑OAuth/PAT。
3. 发布器从GitHub官方HTTPS meta读取SSH host keys，启用严格host-key检查；私库先做可见性检查并以认证SSH证明访问。若库变公开、可见性/网络不明、目标origin不符则停止。
4. 在STATE外的独立目录保留此私库工作树，不把真实数据放进公开源码目录。首次可用bootstrap导出当前状态，不能假装当天已总结。

```sh
python -m personal_bot.vault --root "<STATE>" --worktree "<PRIVATE_VAULT_CHECKOUT>" \
  --repo "<OWNER>/<PRIVATE_REPO>" --ssh-key "<HOST_LOCAL_PRIVATE_KEY>" \
  --architecture-ref "<EXACT_40_HEX_CODE_COMMIT>" --bootstrap
```

每天由真正成功的总结链先调用`companion_summary_done {day,reference}`，再运行同一命令但以`--day YYYY-MM-DD`替代`--bootstrap`。可加`--identity-file`显式保存已授权渠道名册；不自动扫描桥接目录。

出口封锁22端口时，可加`--ssh-transport github443`使用GitHub官方`ssh.github.com:443`。已有HTTP/HTTPS CONNECT代理的宿主用`--ssh-transport github443-proxy`；代理地址与认证仅从现有代理环境变量读取，不写命令参数、日志、Git或SSH配置。服务器密钥仍从官方HTTPS meta获取并严格校验，不关闭校验。[GitHub官方说明](https://docs.github.com/en/authentication/troubleshooting-ssh/using-ssh-over-the-https-port)。不支持CONNECT的代理需由宿主解决正式网络能力，程序不会擅自改变网络策略。

5. 发布器只在受管理的current/和LATEST中暂存并正常commit/push，不force push，不覆盖README或用户未提交改动。只有远端分支实际commit匹配才写回执；状态文件在本机STATE/state/github-vault-receipts.json。
6. 结果不明时保存精确待确认commit，下次先检查其可达性；需要时只推同一个commit，不重新生成同一天的新快照冒充重试。普通重试不会重复每日提交。
7. 将原“发旁聊备份”的任务改为调用发布器，不再向旁聊发一百多个文件。总结后直接调用为主，23:35/04:10可做有界补偿；只能检查/补传已完成总结，不能在补偿时伪造summary_done。

## 继承与限制

私库README应包含docs/INHERITANCE.md的完整流程；代码与数据以commit锁定。原生任务定义只用于参考，不自动激活。SSH key、账号登录态、模型工具权限不继承。

GitHub普通Git单文件限制要求发布器在95MiB停止并报告；不能静默改格式或拆碎SQLite。Git历史可能增长，应按实际用量选择归档策略，删除历史需另行明确处理。当前导出不包含程序运行环境、依赖安装和云端账号权限，因此是完整认知/人格快照，不是整台VM镜像。

去重同时包含真实总结证明与架构commit；同一天真实升级程序后可以生成匹配新版本的快照，不删除旧回执、不伪造新总结。
