"""Isolated regressions; run with the owner's single final acceptance pass."""
import importlib
from pathlib import Path
import sqlite3
import sys
import types
import unittest


PLUGIN = Path(__file__).resolve().parents[1] / 'plugins' / 'social-reading'
PACKAGE = 'voice_trials_fixture_plugin'
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(PLUGIN)]
    sys.modules[PACKAGE] = package
store = importlib.import_module(PACKAGE + '.store')
voice = importlib.import_module(PACKAGE + '.voice')


class VoiceTrials(unittest.TestCase):
    def setUp(self):
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        self.b = types.SimpleNamespace(db=db)
        self.addCleanup(db.close)
        db.execute('''CREATE TABLE source_events(id INTEGER PRIMARY KEY,scope TEXT,
          source TEXT,event_id TEXT,actor TEXT,text TEXT,status TEXT DEFAULT 'active')''')
        store.initialize(self.b)
        voice.initialize(self.b)
        db.execute("INSERT INTO sr_source VALUES('source','tieba','合成论坛','https://tieba.baidu.com/f?kw=fixture',1,1,'verified','{}',1,1,1)")
        self.doc = self.document('one', '这波属于是摆烂了。先停一下，然后换个角度。')

    def document(self, did, quote):
        event = self.b.db.execute('''INSERT INTO source_events(scope,source,event_id,actor,text)
          VALUES('owner-private','plugin:social-reading:fixture',?,'article',?)''', (did, quote)).lastrowid
        self.b.db.execute('''INSERT INTO sr_document VALUES(?, 'source', ?, 'Synthetic thread',
          ?, '{}', ?, ?, NULL, 1, 1, 'complete')''',
                          (did, 'https://tieba.baidu.com/p/' + did, did, quote, event))
        self.b.db.commit()
        return self.b.db.execute('SELECT * FROM sr_document WHERE id=?', (did,)).fetchone()

    def term(self, form='摆烂', **patch):
        item = dict(kind='lexical', form=form, meaning='放弃继续认真投入', variants=[],
                    triggers=['连败'], scenes=['排位游戏'], targets=['自己'], intensity=.5,
                    understood=True, reason='来源语境明确', example='这局我有点想摆烂。',
                    evidence_quote='这波属于是摆烂了。')
        item.update(patch)
        return item

    def learn(self, item=None, doc=None):
        result = voice.learn(self.b, doc or self.doc, [item or self.term()], [])
        return next(r for r in result['habits'] if r['form'] == (item or self.term())['form'])

    def owner(self, message):
        event = self.b.db.execute('''INSERT INTO source_events(scope,source,event_id,actor,text)
          VALUES('owner-private','fixture:owner',?,'user',?)''', (message, message)).lastrowid
        self.b.db.commit()
        return dict(owner_event=event, authorized=True)

    def output(self, turn, seq, text='这局我有点想摆烂。'):
        result = voice.observe_outputs(self.b, [dict(chat_id='native-chat', turn_id=turn,
                   seq=seq, occurred_at_ms=1700000000000 + seq, text=text)])
        return result['outputs'][0]

    def use(self, habit, output, **patch):
        q = dict(habit_id=habit['id'], output_id=output['output_id'],
                 evidence_quote='摆烂', appropriate=True, reason='用于自己的游戏状态')
        q.update(patch)
        return voice.record_use(self.b, q)

    def test_understood_first_source_trials_and_unknown_meaning_stays_candidate(self):
        learned = self.learn()
        self.assertEqual((learned['status'], learned['exposures']), ('trial', 1))
        unknown = self.term('这波属于是', kind='phrase', understood=False,
                            meaning='尚待确认其具体语气', reason='仅此一句，不能确定用法')
        row = self.learn(unknown)
        self.assertEqual(row['status'], 'candidate')
        self.assertEqual(row['reason'], '仅此一句，不能确定用法')
        with self.assertRaises(ValueError):
            self.learn(self.term(evidence_quote='从未真正读到这句'))
        with self.assertRaises(ValueError):
            voice.learn(self.b, self.doc, [self.term()] * 9, [])

    def test_legacy_insert_and_review_preserve_evidence_and_rejected_state(self):
        # A schema extension must not break old positional INSERTs or old thresholds.
        self.b.db.execute("INSERT INTO sr_habit VALUES('legacy','先停再转折','先停顿再换角度','先停。换个角度。','candidate',0,0,1)")
        for n in range(3):
            doc = self.document('legacy-' + str(n), '先停一下，然后换个角度。')
            voice.learn(self.b, doc, [], [dict(existing_id='legacy', pattern='先停再转折',
                        mechanism='先停顿再换角度', example='先停。换个角度。', evidence_quote='先停一下')])
        row = next(r for r in voice.rows(self.b) if r['id'] == 'legacy')
        self.assertEqual(row['status'], 'trial')
        reviewed = dict(habit_id='legacy', document_id='legacy-0', kind='mechanism',
                        form='先停再转折', meaning='用停顿引出另一角度', understood=True,
                        reason='三条原文的停顿结构清楚', evidence_quote='先停一下')
        voice.review(self.b, dict(reviews=[reviewed]))
        self.assertEqual(next(r for r in voice.rows(self.b) if r['id'] == 'legacy')['kind'], 'mechanism')
        with self.assertRaises(ValueError):
            voice.review(self.b, dict(reviews=[dict(reviewed, document_id='one')]))
        self.b.db.execute("UPDATE sr_habit SET status='rejected' WHERE id='legacy'")
        voice.review(self.b, dict(reviews=[reviewed]))
        self.assertEqual(next(r for r in voice.rows(self.b) if r['id'] == 'legacy')['status'], 'rejected')

    def test_owner_teaching_links_actual_owner_quote_without_inventing_document(self):
        auth = self.owner('我教你，摆烂就是放弃认真投入，适合说自己的游戏状态。')
        before = self.b.db.execute('SELECT count(*) FROM sr_document').fetchone()[0]
        item = self.term(evidence_quote='摆烂就是放弃认真投入')
        result = voice.teach(self.b, dict(auth, lexical_candidates=[item]))
        row = result['habits'][0]
        self.assertEqual(row['status'], 'trial')
        self.assertEqual(row['source_proof'][0]['owner_event'], auth['owner_event'])
        self.assertEqual(row['source_proof'][0]['evidence_quote'], '摆烂就是放弃认真投入')
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM sr_document').fetchone()[0], before)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM sr_evidence').fetchone()[0], 0)
        self.assertTrue(voice.teach(self.b, dict(auth, lexical_candidates=[item]))['replayed'])
        with self.assertRaises(ValueError):
            voice.teach(self.b, dict(auth, lexical_candidates=[dict(item, meaning='换个意思')]))
        with self.assertRaises(ValueError):
            voice.teach(self.b, dict(auth, lexical_candidates=[self.term(evidence_quote='论坛上说摆烂')]))

    def test_contextual_retrieval_is_bounded_and_keeps_room_for_new_trials(self):
        forms = ['词甲', '词乙', '词丙', '词丁', '词戊', '词己', '词庚', '词辛']
        doc = self.document('many', '。'.join(forms))
        for index, form in enumerate(forms):
            row = self.learn(self.term(form, evidence_quote=form, example=form), doc)
            if index < 6:
                for number in range(3):
                    self.use(row, self.output(form + '-' + str(number), 1, form), evidence_quote=form)
        selected = voice.voice(self.b, dict(text='排位游戏连败', scene='排位游戏'))
        self.assertLessEqual(len(selected), 6)
        self.assertTrue(any(r['status'] == 'trial' for r in selected))
        # Topic labels rank hints; the same host model decides whether to speak
        # them. Only explicit avoid_contexts is an exclusion, covered below.
        fallback = voice.voice(self.b, dict(text='我要准备银行面试', scene='面试'))
        self.assertTrue(fallback)
        self.assertLessEqual(len(fallback), 6)
        self.assertTrue(any(r['status'] == 'trial' for r in fallback))

    def test_typed_corrections_adjust_context_and_meaning_but_stop_cannot_revive(self):
        row = self.learn()
        correction = self.owner('这个词别用在面试，适合说自己的排位游戏。')
        q = dict(correction, habit_id=row['id'], kind='context',
                 correction=dict(scenes=['排位游戏'], avoid_contexts=['面试']))
        voice.feedback(self.b, q)
        self.assertTrue(voice.feedback(self.b, q)['replayed'])
        self.assertEqual(voice.rows(self.b)[0]['status'], 'trial')
        voice.feedback(self.b, dict(self.owner('语气轻一点。'), habit_id=row['id'], kind='tone',
                       correction=dict(intensity=.2, tone_limit='只轻微自嘲')))
        self.assertEqual(voice.rows(self.b)[0]['intensity'], .2)
        voice.review(self.b, dict(reviews=[dict(self.term(scenes=['面试'], intensity=.9),
                     habit_id=row['id'], document_id='one')]))
        self.assertEqual(voice.rows(self.b)[0]['scenes'], ['排位游戏'])
        self.assertEqual(voice.rows(self.b)[0]['intensity'], .2)
        voice.feedback(self.b, dict(self.owner('以后别再用这个词。'), habit_id=row['id'], kind='stop'))
        voice.feedback(self.b, dict(self.owner('它的意思是放弃认真投入。'), habit_id=row['id'], kind='meaning',
                       correction=dict(meaning='放弃认真投入', understood=True, reason='主人明确纠正')))
        self.learn()
        self.assertEqual(voice.rows(self.b)[0]['status'], 'rejected')
        self.assertTrue(voice.rows(self.b)[0]['stopped'])
        self.assertEqual(voice.voice(self.b, dict(text='排位游戏连败')), [])
        alias = self.learn(self.term('放空打法', variants=['摆烂']))
        self.assertEqual(alias['status'], 'rejected')
        self.assertTrue(alias['stopped'])

    def test_owner_meaning_correction_can_repair_legacy_rejection(self):
        self.b.db.execute("INSERT INTO sr_habit VALUES('old','停顿转折','停顿后引出新角度','先停。换个角度。','rejected',0,1,1)")
        self.b.db.execute("INSERT INTO sr_evidence VALUES('old',?,?,?)", (self.doc['url'], self.doc['id'], '先停一下'))
        result = voice.feedback(self.b, dict(self.owner('这个方法是用停顿引出另一个角度，理解对了可以继续用。'),
                    habit_id='old', kind='meaning', correction=dict(meaning='用停顿引出另一角度',
                    understood=True, reason='主人明确纠正并允许继续')))
        self.assertEqual(result['habit']['status'], 'trial')
        self.assertFalse(result['habit']['stopped'])

    def test_output_receipts_are_idempotent_immutable_and_not_emotional_inputs(self):
        before = self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0]
        output = self.output('turn-a', 1)
        replay = self.output('turn-a', 1)
        self.assertEqual(output['output_id'], replay['output_id'])
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM sr_output').fetchone()[0], 1)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0], before)
        with self.assertRaises(ValueError):
            self.output('turn-a', 1, '修改后的真实输出不能复用同一凭据')
        with self.assertRaises(ValueError):
            voice.observe_outputs(self.b, [dict(chat_id='chat', turn_id='', seq=1,
                                  occurred_at_ms=1700000000000, text='摆烂')])
        row = self.learn()
        debug = self.output('debug', 1, '［Codex调试］词库里有摆烂。')
        with self.assertRaises(ValueError):
            self.use(row, debug)

    def test_only_actual_matching_appropriate_uses_across_two_turns_mature(self):
        row = self.learn()
        for seq in (1, 2, 3):
            self.use(row, self.output('turn-a', seq))
        self.assertEqual(voice.rows(self.b)[0]['status'], 'trial')
        actual = self.output('turn-b', 1)
        self.use(row, actual)
        self.assertTrue(self.use(row, actual)['replayed'])
        matured = voice.rows(self.b)[0]
        self.assertEqual((matured['status'], matured['uses'], matured['native_turns']), ('mature', 4, 2))
        self.assertEqual((matured['exposures'], matured['positive']), (1, 0))
        qualified = voice.qualified_habits(self.b)
        self.assertEqual(qualified[0]['source_proof'][0]['document_id'], 'one')
        self.assertEqual(len(qualified[0]['usage_proof']), 4)
        self.assertTrue(voice.verified_usage(self.b, row['id'], qualified[0]['usage_proof'][0]))
        self.assertTrue(voice.verified_source(self.b, row['id'], qualified[0]['source_proof'][0]))
        self.assertEqual(matured['last_used'], 1700000000.003)
        with self.assertRaises(ValueError):
            self.use(row, actual, appropriate=False)
        with self.assertRaises(ValueError):
            self.use(row, actual, output_id='invented')
        unrelated = self.output('turn-c', 1, '今天心情不错。')
        with self.assertRaises(ValueError):
            self.use(row, unrelated, evidence_quote='今天心情不错')

    def test_private_usage_work_and_correction_invalidate_old_fluency_proof(self):
        row = self.learn()
        for number in range(3):
            self.use(row, self.output('verified-' + str(number), 1))
        proof = voice.qualified_habits(self.b)[0]['usage_proof'][0]
        with self.assertRaises(ValueError):
            voice.usage_work(self.b, dict(scope='shared'))
        voice.feedback(self.b, dict(self.owner('只在自己的排位游戏里用。'), habit_id=row['id'], kind='context',
                       correction=dict(scenes=['自己的排位游戏'])))
        self.assertFalse(voice.verified_usage(self.b, row['id'], proof))
        self.assertEqual(voice.qualified_habits(self.b), [])
        self.assertEqual(voice.rows(self.b)[0]['correction_count'], 1)

    def test_usage_review_is_bounded_revocation_retains_history_and_forgotten_sources_hide(self):
        row = self.learn()
        for number in range(5):
            self.output('turn-' + str(number), 1)
        work = voice.usage_work(self.b, {})
        self.assertLessEqual(len(work['outputs']), 3)
        self.assertIn(row['id'], work['outputs'][0]['habit_ids'])
        for number in range(3):
            self.use(row, self.output('mature-' + str(number), 1))
        self.b.db.execute("UPDATE sr_source SET active=0,status='revoked'")
        self.assertTrue(voice.voice(self.b, dict(text='排位游戏连败')))
        self.assertTrue(voice.qualified_habits(self.b))
        self.b.db.execute("UPDATE source_events SET status='forgotten' WHERE actor='article'")
        self.assertEqual(voice.voice(self.b, dict(text='排位游戏连败')), [])
        self.assertEqual(voice.qualified_habits(self.b), [])
        store.put(self.b, 'policy', dict(language_learning=False))
        count = self.b.db.execute('SELECT count(*) FROM sr_output').fetchone()[0]
        self.output_disabled = voice.observe_outputs(self.b, [dict(chat_id='x', turn_id='x', seq=1,
                           occurred_at_ms=1700000000000, text='摆烂')])
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM sr_output').fetchone()[0], count)
        self.assertEqual(voice.usage_work(self.b, {})['outputs'], [])


    def test_context_keywords_boost_but_do_not_block_a_first_trial(self):
        row=self.learn()
        hints=voice.voice(self.b,dict(text='早上好，吃饭了吗',event_id='ordinary-new-turn'))
        self.assertIn(row['id'],[x['id'] for x in hints])

    def test_unrelated_quote_cannot_support_an_existing_lexical_term(self):
        row=self.learn()
        other=self.document('other','这一局直接重开。')
        with self.assertRaisesRegex(ValueError,'source_mismatch'):
            voice.learn(self.b,other,[self.term(form='重开',existing_id=row['id'],evidence_quote='直接重开')],[])
        # A malformed historical link must not outlive the true original source.
        self.b.db.execute('INSERT INTO sr_evidence VALUES(?,?,?,?)',
                          (row['id'],other['url'],other['id'],'直接重开'))
        self.b.db.execute("UPDATE source_events SET status='forgotten' WHERE id=?",(self.doc['event'],))
        self.b.db.commit()
        actual=next(x for x in voice.rows(self.b) if x['id']==row['id'])
        self.assertEqual(actual['source_proof'],[])
        self.assertEqual(voice.voice(self.b,dict(text='摆烂')),[])

    def test_reference_knowledge_is_not_an_automatic_speaking_habit(self):
        row=self.learn(self.term(usage_mode='reference_only'))
        self.assertEqual(row['status'],'reference')
        self.assertEqual(voice.voice(self.b,dict(text='摆烂')),[])

    def test_long_native_output_is_preserved_without_echoing_full_text(self):
        body='摆烂'+'字'*8000
        r=voice.observe_outputs(self.b,[dict(chat_id='chat',turn_id='long',seq=1,
                                            occurred_at_ms=1700000000000,text=body)])
        self.assertNotIn('text',r['outputs'][0])
        self.assertEqual(self.b.db.execute('SELECT text FROM sr_output').fetchone()[0],body)


if __name__ == '__main__':
    unittest.main()
