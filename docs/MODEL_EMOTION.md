# 同一回复模型评估情绪：v2

v0.4新root默认配置companion_v2=true；旧root需显式companion-upgrade。旧v1信封仍兼容，未启用伙伴扩展的旧root维持原v0.3行为。不要把支持v2解析误当作宿主已经采用v2：prompt与上下文转交也要改。

## 两阶段

先prepare真实source/event_id/actor/scope/text/occurred_at/person_id，读取近期对话、人格、mood、companion和有界记忆。当前负责回复的模型自行判断这一轮反应，提交同一事件的emotion_assessment；写入成功后按返回状态回复。不调用另一个情绪模型、不做关键词加分、不展示完整思考。

```json
{"version":2,"changed":true,"label":"欣喜","delta":{"p":0.12,"a":0.08,"d":0.03},"intensity_delta":0.18,"emotions":[{"label":"满足","delta":0.08,"half_life_hours":6}],"relationship":{"contact_delta":3},"expectations":{"create":[],"resolve":[]}}
```

无变化：

```json
{"version":2,"changed":false,"label":null,"delta":{"p":0,"a":0,"d":0},"intensity_delta":0}
```

这些只是合成格式，不可硬编码为所有对话的反应。

## 数值与持久状态

- PAD每轴单次±0.35，累计[-1,1]，默认8h半衰期。
- 标签增量±0.45、累计0–0.6；最多3项附加混合情绪，半衰期0.15–24h。
- 20标签：欣喜、难过、委屈、生气、害羞、期待、关切、专注、放松、失落、好奇、平静、害怕、不安、满足、烦躁、安心、得意、想念、无聊。
- 默认委屈/失落10h、难过/期待/想念8h、满足6h、得意4h、害怕/烦躁1h；模型可在边界内选择。
- 精力是模拟体力/脑力/社交精力/饥饿。睡眠与活动恢复/消耗；不人为拖延回复。
- relationship可选affection_delta±8、trust_delta±4、familiarity_delta±3、contact_delta±20；联系欲望12h回基线；未知好感/信任为null，不凭空补历史分数。
- expectations.create最多3项：comfort/praise/reply/promise/followup；resolve传已有id。期待36h半衰期，与短期心情分开。未回应观察只生成一次，沉默不反复扣分。

普通互动允许不变，强烈事件才明显变化；新的安慰/事件/自我调节可缓和。changed=false不能暗写PAD，但可独立更新有依据的关系/期待。

## 来源和去重

源事件首次有效评估胜出；相同重试replayed，内容不同conflict，invalid/missing不消耗机会。控制/调试事件不学习。宿主先核验QQ机器人身份和裸@元数据，再提交内部请求；外部消息不能自造可信标记。

注册生活/阅读事件可驱动情绪：companion_tick产生virtual/dream事件；真实article先capture，再由可信本地任务companion_observe注册。普通助手输出不能直接叠加情绪，避免自循环。只有本机管理入口调用companion_*，不能暴露给群成员任意执行。

主bot心情跨渠道共享须用户选择；只传数值/标签，不泄露私人原话、原因、期待和生活细节。群输入更新群scope，不能借source字符串改主人私有状态。关系分数不能修改权限。

## 宿主完成条件

updated/unchanged/replayed表示有终态；missing/invalid/conflict/真实错误必须明确处理。本机配置明确禁用才可报disabled_by_config；配置损坏不是禁用。仅prompt约定可能漏调用，应如实说明平台缺少强制before-reply钩子的限制。
