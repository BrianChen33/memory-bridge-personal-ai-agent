# JSON API ������

������ڣ�`python -m personal_bot --root <STATE> request --file request.json`��Ҳ����stdin��UTF-8 JSON�����β�����65536�ֽڣ��������12000�ַ�����ȡ����е�ok������reason������/��Ĭ/δ�����ǽṹ���������һ���ǳ��������CLI��ok=falseʱ���ط��㣬������JSON�ֶΡ�

����ʱ�� standalone core �������ĵ�����������ʵ��dispatch�����Ƕ����Զ��API������ֵ����ʾ������Ҫ�Ѻϳ�����д����ʽ���˿⡣

## ���ò���

| op | �ؼ��ֶ� | ���� |
|---|---|---|
| prepare | scope/text/source/event_id/occurred_at/actor���ɸ� emotion_assessment v1 | ���� + ���������������� missing����������У��/ȥ�ظ��º󷵻��� mood |
| capture | ͬ�ϣ�actor=user/assistant/bot/article | ����¼��ʵ�¼���emotion=pending_assessment�������������ã����ܳ䵱���ͻ�ִ |
| remember / ingest | scope/text/source/event_id/kind/evidence | �洢�������ļ���/��������֤�� |
| recall | scope/text����ѡstart/end | ����ʱ���������ʽ�뿪���ַ�Χ������ԭ��/����/����Դ�ƶ� |
| correct / forget | scope/id��correct����text/source/event_id | ����/��������ֹ���������ݸ��� |
| mood | scope | ��ȡ˥�����PAD���ǩ������������prepare��ģ���������ɵײ�д����ݽӿڲ������������� |
| derive | scope/sources/text/kind | reflection/skill/lesson����ȷinference����Դ����Ч |
| consolidate | scope/action=propose/merge/undo | Դ��ϣ���顢�ȼۺϲ���ͼ����ͻ������ |
| vector_index | scope/limit<=20 | �����н��̨������ģ�Ͳ����þ�ʧ��/�����ؼ��� |
| reading | scope=owner-private/action=claim/commit/status | �������ĵ��Ķ�����Լ��ԭ�����ƶϱʼǡ��α� |
| reminder | scope=owner-private/action | �����������ڣ����� |
| proactive_check | scope=owner-private | ʵ��ϵͳʱ����background_allowed/can_notify |
| life / news | scope=owner-private��ʵ��sources/�����ֶ� | ���ɴ�������ѡ��news����֤��ǰ����/����/��ֵ |
| digest_claim / digest_authorize / digest_finish | scope/channels/lease/epoch/expressed_ids | ����ڹ�������/ȥ�غ�������Դ���� |
| maintain | scope | �鵵���ڵ���Ҫ�Ե�episode |

`source` ����Դ��¼����������ѧ��֤�����ݺͲ�����Ȩ�������������Ŀ��������������������߼����룬ӵ�б���ִ��Ȩ�޵�ͬһ�������ܶ������ļ������Ƕ��⻧��ȫ�߽硣

## ʱ��������

ͬһ��ʵ��Ϣ��������scope/source/event_id/actor�����ݱ����ܾ����������� prepare Ԥ��������ԭ�ظ�ģ���ύͬ�¼� emotion_assessment��û�йؼ����Զ����¡�updated/unchanged/replayed �ɼ�����missing/invalid ��Ҫ����Ч������conflict �����׸���legacy_recorded ��ʾ����ǰ�Ѹ��¹��ľ��¼��������ظ�Ӧ�á���ֵ���޷���PAD��Сʱ��˥����ǩ45���Ӱ�˥���ޱ仯�ʹ���ȡ����״̬ʱ�䡣��ϸЭ�顢����JSON��Ǩ�Ʊ߽�� [MODEL_EMOTION](MODEL_EMOTION.md)��

`recall {text:"����������˵��ʲô"}` ������ʱ��5�C12��ȡ����userԭ����`{start:...,end:...}`����ʹ����ȷ��Χ��insights���ʼ�����occurred_at���ˣ�������ԭʼ��ԴID�������ƶϵ��û�ԭ����û�м�¼�ͻش�û��Դ��¼��

## ���ѱջ�

1. `reminder/create`��textΪԭʼʱ������bodyΪԤ��д�õ����ģ�source/event_idΪʵ��������Դ���硰�������㡱����ȷ�����磬����needs_clarification�����ܲ¡�
2. ledger����id/version/native_job_id/native_at/timezone�������Ȳ�ͬIDԭ��runonce���ٴ������á�view�˶Ժ�`reminder/attach`��
3. runonceִ�У�`python -m personal_bot --root <STATE> reminder --id ID --version N --handoff`�����ȴ�900�룬ʵ�ʵ���󸴲����á��汾��ȡ����epoch����Ĭ����Լ����ǰ���Ѳ���ǰ����
4. ��ok=true/status=unknownʱ�������ѷ���bodyԭ����Ϊһ��native final��unknown����׼�����ӣ����ǿͻ��˻�ִ�������Զ����ԡ�
5. `cancel`��Χ������ͣ���ص�native job��`ack_disabled`��`reschedule`����version��ͣ����ID��������version���ȶ�ID��attach��
6. `pending`���ָ�������ˣ�������5m���˴���runonce��ʱ��lifeģ����ͣ��Ӧȡ���û���ȷ��������ѣ��ܿ���/���ѹ��ܹرջ���ֹ���ӡ�

Ĭ��ҹ�����ڵ�07:00��ֻ���û���ȷָ��ҹ������ʱ����������Ŵ�quiet_override=true��quiet_permission=explicit_user_request����Ҫ�Ӽ��������ƶ�����Ȩ�ޡ�

## �Ķ��ջ�

��`<STATE>/library/`��������Ȩ�Ĺ���UTF-8�ı�/Markdown���Ǽ�reading-sources.json��

```json
{"version":1,"documents":[{"id":"sqlite-backup","path":"library/sqlite-backup.txt","source_url":"https://www.sqlite.org/backup.html","public":true}]}
```

`reading/claim`���ؾ�ȷtext/source_hash/start/end/lease������ʵ���Ķ�����chunk_id/lease/summary����commit�������ٴκ˶�Դ�ļ���ԭ��дepisode/observedԭ�ĺ�reflection/inference�ʼǣ���ǰ��cursor��ʧ�ܲ�ǰ�����ظ��ύ���ظ�д��Դ�ѱ�����������졣

�ʼǿ���`life {sources:[quote_id],topic:"reading:�ĵ�:��ϣ:λ��",text:�м�ֵ�۲�}`��ӣ���reading channel����gate����������Ų���ð���Ķ��ƹ�����/��ֵ��

## �ȼۺϲ�

proposeֻ����ѡ��merge�����ṩͬscope������kind/evidence��ids��ÿԴ��ǰfingerprint��hashes����ȷquotes��relation=equivalent��contradiction����ȷreason������/���ڻ�񶨱仯����Ϊconflict��ԭ�Ĳ���д��undoֻ����ͼ����������forgotten/superseded��Դ��

## ����Լ��

digest_claim��channels��ȡlife/news/emotion/reading����ͬ����ֻ�����Լ���channel��ȡ��lease/epoch������Դ���ɣ���authorize��finish unknown��expressed_idsֻ���ʵ�ʱ����ID��δ�ú�ѡ������������һ������ԴʧЧ������/��ֵ�ı��羲Ĭ�߽�ʱ�������ؾܾ�����Ҫ���в�����

��������ʹ��`personal_bot backup`����Ҫ���ײ�ɵ�op=backup����SQLite�����������ݡ�
