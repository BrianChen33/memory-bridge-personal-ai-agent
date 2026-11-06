"""Grounded habit consolidation; run only in the final isolated acceptance."""
import importlib
import json
from pathlib import Path
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import uuid


PLUGIN = Path(__file__).resolve().parents[1] / 'plugins' / 'social-reading'


class HabitGrowth(unittest.TestCase):
    def setUp(self):
        self.package = '_habit_growth_' + uuid.uuid4().hex
        package = ModuleType(self.package)
        package.__path__ = [str(PLUGIN)]
        sys.modules[self.package] = package
        self.addCleanup(self.clean_modules)
        self.store = importlib.import_module(self.package + '.store')
        self.voice = importlib.import_module(self.package + '.voice')
        self.growth = importlib.import_module(self.package + '.habit_growth')
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        self.b = SimpleNamespace(db=db)
        db.execute('''CREATE TABLE source_events(id INTEGER PRIMARY KEY, actor TEXT,
          scope TEXT,status TEXT,text TEXT)''')
        self.store.initialize(self.b)
        self.voice.initialize(self.b)
        self.growth.initialize(self.b)
        self.sequence = 0
        db.execute("INSERT INTO source_events VALUES(1,'article','owner-private','active',?)",
                   ('游戏连败时，我偶尔想摆烂，指不再认真投入。',))
        db.execute("INSERT INTO source_events VALUES(2,'user','owner-private','active','允许阅读合成论坛')")
        db.execute('''INSERT INTO sr_source VALUES('fixture-source','tieba','合成论坛',
          'https://tieba.baidu.com/f?kw=fixture',2,1,'verified','{}',0,1,0)''')
        db.execute('''INSERT INTO sr_document VALUES('fixture-doc','fixture-source',
          'https://tieba.baidu.com/p/100','Synthetic source','hash','{}',?,1,10,0,0,'ok')''',
                   ('游戏连败时，我偶尔想摆烂，指不再认真投入。',))
        db.commit()

    def clean_modules(self):
        for name in list(sys.modules):
            if name == self.package or name.startswith(self.package + '.'):
                sys.modules.pop(name, None)

    def enable(self):
        with self.b.db:
            self.store.put(self.b, 'policy', {'personality_growth': True})

    def habit(self, form='摆烂'):
        doc = dict(self.b.db.execute('SELECT * FROM sr_document').fetchone())
        if form not in doc['quote']:
            with self.b.db:
                self.b.db.execute('UPDATE sr_document SET quote=quote||?', (' ' + form,))
                self.b.db.execute('UPDATE source_events SET text=text||? WHERE id=1', (' ' + form,))
            doc = dict(self.b.db.execute('SELECT * FROM sr_document').fetchone())
        learned = self.voice.learn(self.b, doc, [dict(kind='lexical', form=form,
            meaning='在连败后暂时不认真投入的自嘲', variants=[], triggers=['连败'], scenes=['游戏'],
            targets=['自己'], intensity=.5, understood=True, reason='实际上下文清楚',
            example='我想' + form, evidence_quote=form)], [])
        return next(h['id'] for h in learned['habits'] if h.get('form') == form)

    def use(self, hid, turn=None, form='摆烂'):
        self.sequence += 1
        result = self.voice.observe_outputs(self.b, [dict(chat_id='fixture-chat',
            turn_id=turn or 'turn-' + str(self.sequence), seq=self.sequence,
            occurred_at_ms=1700000000000 + self.sequence, text='连败了，我想' + form)])
        output = result['outputs'][0]['output_id']
        self.voice.record_use(self.b, dict(habit_id=hid, output_id=output,
            evidence_quote=form, appropriate=True, reason='实际游戏情境里的自嘲'))
        return output

    def mature(self, form='摆烂'):
        hid = self.habit(form)
        for _ in range(3):
            self.use(hid, form=form)
        return hid

    def proposal(self, hid):
        return self.growth.work(self.b, {'habit_ids': [hid]})

    def integrate(self, work, hid, **changes):
        request = dict(proposal_id=work['proposal_id'], habit_ids=[hid], domain='temperament',
            trait='遇到挫折时更愿意轻松自嘲', interpretation='多次实际使用适合自己，但不把放弃当信条。',
            example='游戏连败时承认沮丧，开句玩笑后再决定休息或继续。', resonance=1., direction='adopt')
        request.update(changes)
        return self.growth.integrate(self.b, request)

    def test_opt_in_and_actual_fresh_usage_are_required_before_any_trait(self):
        hid = self.habit()
        self.assertEqual(self.growth.work(self.b, {})['habits'], [])
        self.enable()
        self.use(hid, turn='same')
        self.use(hid, turn='same')
        self.use(hid, turn='same')
        self.assertEqual(self.proposal(hid)['habits'], [])
        self.use(hid, turn='second')
        ready = self.proposal(hid)
        self.assertEqual(len(ready['habits']), 1)
        self.assertGreaterEqual(len(ready['habits'][0]['usage_proof']), 3)
        self.assertEqual(self.growth.rows(self.b), [])
        self.assertEqual(self.growth.context(self.b)['traits'], [])

    def test_same_proposal_and_same_native_evidence_cannot_grow_again(self):
        self.enable()
        hid = self.mature()
        ready = self.proposal(hid)
        first = self.integrate(ready, hid)
        self.assertEqual(first['applied'], 1)
        self.assertAlmostEqual(first['traits'][0]['strength'], .02)
        self.assertTrue(self.integrate(ready, hid)['replayed'])
        self.assertEqual(self.proposal(hid)['habits'], [])
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.integrate(ready, hid, trait='从同一词硬推出来的另一个性格')
        self.assertAlmostEqual(self.growth.rows(self.b)[0]['strength'], .02)

    def test_reconsider_reduces_the_same_trait_and_needs_new_evidence(self):
        self.enable()
        hid = self.mature()
        first = self.integrate(self.proposal(hid), hid)
        gid = first['traits'][0]['id']
        for _ in range(3):
            self.use(hid)
        revised = self.integrate(self.proposal(hid), hid, direction='reconsider',
            existing_id=gid, trait='不创建反方向的人格', resonance=.5)
        self.assertEqual(len(revised['traits']), 1)
        self.assertEqual(revised['traits'][0]['id'], gid)
        self.assertEqual(revised['traits'][0]['trait'], '遇到挫折时更愿意轻松自嘲')
        self.assertAlmostEqual(revised['traits'][0]['strength'], .01)
        for _ in range(3):
            self.use(hid)
        with self.assertRaisesRegex(ValueError, 'existing'):
            self.integrate(self.proposal(hid), hid, direction='reconsider', existing_id='missing')

    def test_habit_rejection_hides_overlay_while_browse_revocation_retains_learning(self):
        self.enable()
        hid = self.mature()
        self.integrate(self.proposal(hid), hid)
        before = self.growth.context(self.b)
        self.assertEqual(len(before['traits']), 1)
        with self.b.db:
            self.b.db.execute("UPDATE sr_habit SET status='rejected' WHERE id=?", (hid,))
        self.assertEqual(self.growth.context(self.b)['traits'], [])
        self.assertEqual(len(self.growth.rows(self.b)), 1)
        with self.b.db:
            self.b.db.execute("UPDATE sr_habit SET status='mature' WHERE id=?", (hid,))
            self.b.db.execute("UPDATE sr_source SET active=0,status='revoked'")
        self.assertEqual(len(self.growth.context(self.b)['traits']), 1)
        self.assertEqual(self.growth.context(self.b)['revision'], before['revision'])

    def test_source_forgetting_and_personality_opt_out_hide_existing_cues(self):
        self.enable()
        hid = self.mature()
        self.integrate(self.proposal(hid), hid)
        with self.b.db:
            self.b.db.execute("UPDATE source_events SET status='retired' WHERE id=1")
        self.assertEqual(self.growth.context(self.b)['traits'], [])
        with self.b.db:
            self.b.db.execute("UPDATE source_events SET status='active' WHERE id=1")
            self.store.put(self.b, 'policy', {'personality_growth': False})
        self.assertFalse(self.growth.context(self.b)['enabled'])
        self.assertEqual(self.growth.context(self.b)['traits'], [])
        self.assertEqual(self.integrate(self.proposal(hid), hid)['applied'], 0)

    def test_missing_actual_output_cannot_be_integrated(self):
        self.enable()
        hid = self.mature()
        ready = self.proposal(hid)
        with self.b.db:
            self.b.db.execute('DELETE FROM sr_output')
        self.assertEqual(self.growth.integrate(self.b, {})['applied'], 0)
        with self.assertRaisesRegex(ValueError, 'stale|evidence'):
            self.integrate(ready, hid)
        self.assertEqual(self.growth.rows(self.b), [])

    def test_context_correction_invalidates_the_pending_profile_revision(self):
        self.enable()
        hid = self.mature()
        ready = self.proposal(hid)
        with self.b.db:
            self.b.db.execute("INSERT INTO source_events VALUES(3,'user','owner-private','active','只在单人游戏里自嘲，不对队友说')")
        self.voice.feedback(self.b, dict(habit_id=hid, owner_event=3, authorized=True,
            kind='context', correction={'scenes': ['单人游戏'], 'targets': ['自己']}))
        with self.assertRaisesRegex(ValueError, 'stale|evidence'):
            self.integrate(ready, hid)
        self.assertEqual(self.growth.rows(self.b), [])

    def test_old_verified_receipts_survive_bounded_recent_usage_and_source_projection(self):
        self.enable()
        hid = self.mature()
        self.integrate(self.proposal(hid), hid)
        for _ in range(24):
            self.use(hid)
        for n in range(9):
            event = n + 10
            with self.b.db:
                self.b.db.execute("INSERT INTO source_events VALUES(?,'article','owner-private','active','摆烂')", (event,))
                self.b.db.execute('''INSERT INTO sr_document VALUES(?, 'fixture-source', ?,
                  'Synthetic later source', ?, '{}', '摆烂', ?, NULL, ?, ?, 'ok')''',
                    ('later-' + str(n), 'https://tieba.baidu.com/p/' + str(200 + n), str(n), event, event, event))
                self.b.db.execute('INSERT INTO sr_evidence VALUES(?,?,?,?)',
                    (hid, 'https://tieba.baidu.com/p/' + str(200 + n), 'later-' + str(n), '摆烂'))
        context = self.growth.context(self.b)
        self.assertEqual(len(context['traits']), 1)
        self.assertAlmostEqual(context['traits'][0]['strength'], .02)
        self.assertIn(1, context['traits'][0]['evidence']['source_events'])

    def test_proposals_are_bound_to_real_evidence_and_zero_resonance_adds_no_trait(self):
        self.enable()
        hid = self.mature()
        ready = self.proposal(hid)
        self.assertEqual(ready['proposal_id'], self.proposal(hid)['proposal_id'])
        with self.assertRaisesRegex(ValueError, 'habit'):
            self.integrate(ready, 'invented-habit')
        for resonance in (True, -.1, 1.1, float('nan')):
            with self.assertRaisesRegex(ValueError, 'resonance'):
                self.integrate(ready, hid, resonance=resonance)
        self.assertEqual(self.integrate(ready, hid, resonance=0)['applied'], 0)
        self.assertEqual(self.growth.rows(self.b), [])
        self.assertEqual(self.proposal(hid)['habits'], [])

    def test_existing_reading_growth_and_habit_growth_share_the_daily_budget(self):
        self.enable()
        hid = self.mature()
        with self.b.db:
            self.b.db.execute("INSERT INTO sr_growth VALUES('old','temperament','旧倾向','反思','示例',0,0)")
            self.b.db.execute("INSERT INTO sr_growth_evidence VALUES('old','url','fixture-doc',.055,'摆烂','反思',0,'2026-11-06')")
        with patch.object(self.growth.time, 'time', return_value=1793923200):
            result = self.integrate(self.proposal(hid), hid)
        self.assertAlmostEqual(result['traits'][0]['strength'], .005)
        self.assertAlmostEqual(self.growth.spent(self.b, 'temperament', '2026-11-06'), .005)

    def test_owner_stop_is_permanent_and_keeps_the_review_receipt(self):
        self.enable()
        hid = self.mature()
        first = self.integrate(self.proposal(hid), hid)
        gid = first['traits'][0]['id']
        with self.b.db:
            self.b.db.execute("INSERT INTO source_events VALUES(3,'user','owner-private','active','停止这个成长倾向')")
        self.growth.feedback(self.b, dict(growth_id=gid, owner_event=3, authorized=True, polarity='stop'))
        self.assertEqual(self.growth.context(self.b)['traits'], [])
        self.assertEqual(self.growth.rows(self.b)[0]['status'], 'stopped')
        for _ in range(3):
            self.use(hid)
        again = self.integrate(self.proposal(hid), hid, existing_id=gid)
        self.assertEqual(again['applied'], 0)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM sr_habit_growth_receipt').fetchone()[0], 2)

    def test_context_is_bounded_and_cites_output_and_source_references(self):
        self.enable()
        forms = ('摆烂', '重开', '绷住', '歇会儿')
        habits = [self.mature(form) for form in forms]
        self.assertEqual(len(self.growth.work(self.b, {})['habits']), 3)
        for n, (form, hid) in enumerate(zip(forms, habits)):
            with patch.object(self.growth.time, 'time', return_value=1793923200 + n * 86400):
                self.integrate(self.proposal(hid), hid, domain='preference', trait='偏好' + form)
        self.assertEqual(len(self.growth.rows(self.b)), 4)
        context = self.growth.context(self.b)
        self.assertLessEqual(len(context['traits']), 3)
        self.assertTrue(context['traits'])
        evidence = context['traits'][0]['evidence']
        self.assertIn(1, evidence['source_events'])
        self.assertTrue(evidence['output_ids'])
        self.assertTrue(evidence['habit_ids'])
        self.assertLess(len(json.dumps(context, ensure_ascii=False)), 6000)


if __name__ == '__main__':
    unittest.main()
