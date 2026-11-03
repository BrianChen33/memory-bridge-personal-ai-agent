# Muse / Dot����������

�������Ǹ��� AI �����壬���弰�ٷ���Դ�� [TERMINOLOGY](TERMINOLOGY.md)�������ǿ�ʵ�ֵĽӿ���Լ������ Muse / Dot ��ͨ�ùٷ� SDK��

## �����벿��λ��

Muse �Ĳο�������ִ�б��������д�ļ�������ԭ����ʱ���������˺�/�汾�����ʵ�ʹ��� schema ��飬���ܼ���·��Ϊĳ���̶� home��Ҳ���ܰѲο�ʵ�������� ID �����踴�ƹ�ȥ��

OpenAI �� [�ٷ� dot �ĵ�](https://learn.chatgpt.com/docs/dots/computers-and-apps) ˵�����ƶ˵����뱾�������������������Ƿ�ɰ�װ�������Ƿ��г������̡���ε���/���ͣ���Ҫ��Ŀ�껷�����ʵ�ʹ��ߺ�Ȩ�ޡ�ӵ���ƶ˵��Բ�����������չ���йٷ��Զ���װ�ӿڡ��˲ֿⲻ�鹹 dot ��˽���ļ�λ�û�ԭ������д��ӿڡ�

���ֻ��ʹ��ֻ�� MCP��ԭ `memory_bridge` �� memory_search ֻ������������׼�Ľ����⣻���������� personal_bot ��д��/����/���Ƚӿڡ���Ҫ����������·�߱���Ϊ�������롣

## ����Ŀ¼�����Ŀ¼

`personal_bot` ���Ѱ�װ�� Python ����`<STATE>` �Ƕ����ı�������Ŀ¼����Ҫ������������ home��`init` ������ԭ�е��˸���ʷ��ϵͳ���򣬷Ǳ�����ӵ�еķǿ�Ŀ¼�ᱻ�ܾ���

`doctor` ���� code_root/data_root�������߿��Ծݴ˶�λ��ѡ Node �����ļ�����������ֻ�ܸ���С���ã��ȱ���ԭʼ�ֽ����ϣ������¼Ŀ�꼰��װ���ϣ��ʵ�ʼ�¼������ `<STATE>/state/deployment.json` �� host_manifests/owned_native_jobs ���ֶΣ������ǿɱ䰲װ��¼���������Ա��˵Ĺ̶������嵥��

## ÿ����ʵ��վ��Ϣ

�ȹ���Ԥ�� JSON ��ͨ�� `python -m personal_bot --root <STATE> request --file <REQUEST>` ���ã�

```json
{
  "op": "prepare",
  "scope": "owner-private",
  "source": "main:my-agent",
  "event_id": "stable-platform-message-id",
  "occurred_at": 1700000000.123,
  "actor": "user",
  "text": "������ԭ��"
}
```

- scope �����ɿ�������/ʵ�ʻỰӳ�����ɣ������������Ա��ġ��������ˡ�������˽���� owner-private��QQ ������˽��/Ⱥ�ֱ��� qq:c2c:ID / qq:group:ID��
- event_id ������ʵ���ȶ� ID���������á�û�г��� ID ʱ��������������������ʵ��Ϣ�뱾�� ID ��ӳ�䣬����ÿ������������ UUID��
- occurred_at ��ԭʼ Unix **��**��QQ inbox ������ ts �Ǻ��룬����������1000����Ҫ�ѽ���ʱ�̻��ļ� mtime ð����֪����ʷ����ʱ�̡�
- ��������α�쳣פ�Զ� hook�������������ÿ���ȵ��ù��ߣ��Ͱ���ʵ Message ID/ʱ��� prepare������ʵ�����ոõ��÷�����������ֻ��һ��˵����˵�Ӻ��ˡ�
- ����/����/�ϳ����ݴ� control=true �� synthetic=true������Ϊ�û�����/��ʵ��Դ��

���ص� memories ���ѹ۲�/ȷ�ϵļ�¼��insights ����ԭʼ��Դ���ƶϣ�events ��ԭ�����ֱ�ʹ�á�mood/style �������ο��������������Լ��ļ������衣

**v0.3 �����ٽ�ģ���������裺** �״����������� emotion.status=missing���������ԭ���Զ���������ԭ�ظ�ģ�ͽ�������������ڶԻ������� [emotion_assessment v1](MODEL_EMOTION.md)������ͬ�¼�Ԫ�������ص� prepare����ȡ updated/unchanged/replayed ���� mood ������֯�ظ�������Ӳ����̶�������Ҳ���ܰ�ȱʧ����������ģ���ж�û�仯�������ֻ����ʾ�������ǿ�ƹ��ӣ���ȷ˵������©���ã���ͨ���첻չʾ���ֻ�JSON���Լ�������������ύ�����ޱ仯�ŷ⣬�������ҵ���������

�������Ķ� changed=true ������ user �¼����������������ˡ���������ͶӰ�ͱ���ý��������Ŀ����������ʵ������Ȩ�����β���ֲ Muse �� QQ ר����·���ɿ�ѡ QQ prepare ������ֻ��Ԥ�������ܽ���������г�Ϊ�������������롣

��Ϣ����ѧϰ���� ingest/remember�����뱣�� source/event_id/kind/evidence����Ҫ�������ܽ�ֱ������Ϊ�û�ȷ����ʵ������δ�����ͼ�¼��δ����������Ҫ�����ݡ�

## ��ѡ QQ ����

`personal_bot/runtime/qq-adapter.mjs` ���� enhance/prepareRequest/enqueueLearning��learn.mjs ���� drainLearning����Ҫ�������ṩ�����ݺ���� prepared.inbox �� sender_identity�����ֿⲻ���� QQ token��Webhook ����people.json ���Զ��� QQ ����Ȩ�ޡ�

```js
import {enhance, enqueueLearning} from '/ABS_CODE_ROOT/runtime/qq-adapter.mjs';
import {drainLearning} from '/ABS_CODE_ROOT/runtime/learn.mjs';
const context = enhance(prepared, {
  root: '/ABS_PRIVATE_DATA_ROOT',
  codeRoot: '/ABS_CODE_ROOT/runtime',
  python: '/ABS_VENV/bin/python'
});
```

`codeRoot` Ĭ����ģ���������ڵ� runtime���ɲ�����ͬ����ǿ�ܳ�ʱ��Ϊ450ms����/����ʱ����ԭ�ظ����̣��������µ�ģ���ִΡ�ȷ��ԭQQ�ظ��ɹ������ enqueueLearning����̨ drainLearning Ҫ��ʵ�� bridgeDir �� qq-prepare.mjs �ٺ������ݺ�Դ�ļ���ʧ�ܸ��룬�����·�QQ��Ϣ��

��Щ���벻�����͡��޸� Markdown ���ͻ�ǿ�� @ ���򡣲�Ҫ��ĳ�������ߵ� QQ ��ʾ�����Զ��׸����������ˣ���ԭ�ű������е����ݺͷ����߼���

## �������������

�� init ���ɵ� scheduler-blueprint��6����ȫdisabled�����ֶ� mode/schedule/delivery ��������ͼ�����뷭��Ϊ����ʵ�ʹ��ߣ��������ȷ�ϡ������� current����disabled���� historical/archive ����ֿ����� state/native-schedules.json������ֻ����ǰ��ʾ��10����������

������������̨����������Դ�ĺ�ѡ����channel��������ɡ�authorize��finish unknown��ֻ����ʹ���������һ��native final�����һ��û�е��ͻ�ִʱ��ֻ�ƽ���״̬δ֪�������û����յ������Ա������ʽ������Ϣ�ֿ��������� unknown��

���ѵ������ڴ���ʱд�ã��ȶ�native ID�ڴ�����view��attach��ȡ��/�����ȸ���ledger��`personal_bot reminder --handoff` ��һ�����ؽ�����ִ��due wait��claim��authorize��handoff�����ٹ����ִΡ�ֻ��ok=true/status=unknownʱ��bodyԭ�����һ�Ρ�ԭ�����ȿ�����ǰҲ������������ֻ�ܷ�ֹ��ǰ���ӣ����ܳ�ŵ�ͻ���׼����ʾ��

## ��ʱ����˵����ɲ���

Ҫ�ֱ���������ز��ԡ���ʵ����վ��prepare������ʵ��д�롢ʱ��ԭ����ѯ��source/evidence����ʵԭ��������/����״̬��һ�����ѽ��ӡ���ʵ�Ķ����αꡢ�������ݻָ������˼�¼��

�״���Ȼ2h/�賿������δ������дδ��Ȼ���ա�û��shell/����/����ʱ�г�ȱʧ���������ܿ�����������Ч����������֤�ݡ��ο���������֤��194����Ĳ��ԣ����������ƽ̨�Զ�֧����Щ������
