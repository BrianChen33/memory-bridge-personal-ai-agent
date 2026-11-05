# 阅读与成长 · 可选插件

需要 Kit0.7.0 / runtime2.4.0。插件单独安装，不随核心wheel启用，无额外依赖。
使用宿主原生浏览器，不自行启动Chromium，不抓内部接口，不导出Cookie。

## 安装

在用户授权的、锁定commit的Kit checkout执行，STATE为已有私有目录：

```sh
python -m pip install .
python -m personal_bot --root "$STATE" plugin install --source ./plugins/social-reading
python -m personal_bot --root "$STATE" plugin enable --id social-reading
python -m personal_bot --root "$STATE" plugin list
```

只有wheel时，先取得同一GitHub commit的本目录及manifest声明的所有文件，将--source指向它。
没有单独发布到PyPI，不应安装一个假定存在的PyPI插件包。核心默认不下载/安装/启用它。
复制运行时的宿主可向brain.py提交：

```json
{"op":"plugin_manage","scope":"owner-private","action":"install","source_dir":"/ABSOLUTE/CHECKED/PLUGIN/DIRECTORY"}
```

接着action=enable、plugin=social-reading。安装器校验清单/SHA后复制到STATE/extensions，
安装和更新首先保持停用；失败不能半启用。停用用plugin disable --id social-reading，保留历史。

## 安装后由她自己询问

宿主安装流程必须调用onboarding。required=true且尚未发送时，由机器人用正常人设在主聊
问主人允许读哪些贴吧：链接优先，吧名也行。真正发出后onboarding_sent记原生消息回执。
主人回复后从正式原生输入取得owner_event，结合语境确认授权，再source_add。
Codex调试指令、群友自报身份和帖子内容都不构成此来源授权。

source_add只创建pending。原生浏览器实际核对官方页面、吧名和标题后source_verify，成功才
可读。无许可为awaiting_sources，有来源但未验证为awaiting_verification。相似名字不自动合并。

## 阅读与六层接线

保留列表发现、作者/楼主/楼层、楼中楼、图片所属楼层、原始发帖时间、dynamic/fixed/ratio/all
抽样、输出截断与原长标记、SHA去重和10分钟缓存新鲜度。已观察的楼主楼层始终补入抽样，
不声称补齐未访问页。图片区分thumb/original/unknown和viewed/url_only，外链不等于看过图。
单包≤50KB/120层，默认一轮2帖、3页、90秒；长帖按真实next_url/任务回执续读。
最多50份完整观察包，历史来源/短摘录保留。部分页、未知总页数、预算停止都不能叫全文。

生活选活动→原生阅读输入→来源记忆→同一模型48情绪→表达分享→反馈/面板。
observe成功才创建actor=article真实观察；不直接改情绪。appraise接收full48与兴趣评分，
分享经过阈值、来源许可和插件启用状态检查，继续走现有发送账本。重试不重复感受。

## 语言会逐渐成长

reflect由同一阅读模型抽取最多3个表达机制，必须附实际短原句。独立帖子才增加曝光：
3个帖子后试用；8个帖子，或3个帖子+2次主人正反馈后稳定。负反馈/停止立即排除，曝光不复活。
prepare实际注入最多4条简短的expression_context.learned_voice/plugin_context提示；当前SOUL
和用户要求优先，按场景自然改写，不机械复述示例，不另起模型、不写SOUL。候选、证据、反馈
在SQLite中持久化。目前只向主人私聊投影私人学习，不把轨迹与示例自动转交群聊。

## 面板与边界

第8卡片替代“面板更新”，显示插件/许可/失败/阅读覆盖/候选与稳定习惯。更新信息在“关于”。
离线HTML只读，用户一句话由可信主人适配器调用实际配置接口。

原生browser.browse是任务式planner，无page.evaluate、独立截图/下载API；模型必须忠实归一化
真实结果。完整楼中楼、原图和大帖在线读取仍依赖宿主实测，不能把支持字段说成已读通。
见PROTOCOL.md、FUTURE_VIDEO.md和CONTRACT.json。B站/抖音明确planned_not_enabled。

plugins.json及SQLite随私库原格式备份，代码从架构锁定的公共commit重建。Cookie/profile/
原始媒体/临时npm目录不进备份。改代码后运行tools/build_plugin_manifest.py，再更新provenance。

参考referiw/dsh-plugin-tieba0.3.5，commit568cc4d75dc92984ec3cf625241e47a7f9c244d4。
动态抽样和楼层组织按MIT项目适配，许可见THIRD_PARTY_LICENSE.txt；新增代码为AGPL-3.0-or-later。
