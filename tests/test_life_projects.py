"""Isolated project regressions; no external models, browser or delivery."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from personal_bot import deploy
sys.path.insert(0, str(deploy.RUNTIME))
from brain import Brain
from muse_ext import companion as c, life_projects as p


class LifeProjects(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='life-projects-isolated-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'state'
        deploy.init(self.root)
        deploy.enable(self.root, list(deploy.DEFAULT_FEATURES))
        self.b = Brain(self.root)
        self.addCleanup(self.b.close)
        p.initialize(self.b)
        self.clock = patch.object(c, 'stamp', return_value=1800000000.0)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.current = dict(name='写小故事', started_at=self.now.return_value,
                            ends_at=self.now.return_value + 1200, origin='virtual',
                            cost=[-1, -9, 3, 2], outcome='legacy outcome must stay unused')
        self.pid = p.register(self.b, self.current)
        c._set(self.b, 'life', dict(activity=self.current, next_at=0))
        self.b.db.commit()

    def call(self, action, **values):
        return p.dispatch(self.b, dict(action=action, project_id=self.pid, **values))

    def plan(self):
        return dict(version=1, origin='virtual', activity='写小故事', topic='给月亮修理钟表的猫',
                    stages=[dict(after_seconds=300, description='FIRST-VISIBLE 写下修钟猫推开月亮店门的开头。'),
                            dict(after_seconds=600, description='SEALED-SECOND 猫把坏钟的影子剪成了新指针。')],
                    artifact=dict(title='月亮钟表店', text='NATIVE-ARTIFACT 猫在月亮上开了一间钟表店。\n坏钟的影子变成了新指针。'))

    def test_drafts_never_enter_normal_context_recall_or_source_events(self):
        plan = self.plan()
        result = self.call('plan', expected_version=0, plan=plan)
        self.assertEqual(result['project']['status'], 'active')
        self.assertEqual(c.context(self.b,'owner-private')['activity']['name'],'写小故事')
        ordinary = [result, self.call('view'), self.call('pending'), c.context(self.b, 'owner-private'),
                    self.b.dispatch(dict(op='recall', scope='owner-private', text='SEALED-SECOND'))]
        for value in ordinary:
            self.assertNotIn('SEALED-SECOND', json.dumps(value, ensure_ascii=False))
            self.assertNotIn('NATIVE-ARTIFACT', json.dumps(value, ensure_ascii=False))
        self.assertNotIn('SEALED-SECOND', '\n'.join(r[0] for r in self.b.db.execute('SELECT text FROM source_events')))
        original = self.b.db.execute('SELECT payload FROM ct_activity_plan WHERE project=? AND version=1', (self.pid,)).fetchone()[0]
        self.assertEqual(json.loads(original), plan)
        self.assertLessEqual(len(json.dumps(self.call('view')['project'], ensure_ascii=False)), 1200)
        self.assertIsNone(c.context(self.b, 'qq:group:fixture')['activity'])

    def test_due_projection_and_canonical_events_are_idempotent(self):
        self.call('plan', expected_version=0, plan=self.plan())
        self.now.return_value += 301
        visible = self.call('view')['project']
        self.assertIn('FIRST-VISIBLE', json.dumps(visible))
        self.assertNotIn('SEALED-SECOND', json.dumps(visible))
        first = p.advance(self.b, self.now.return_value)
        self.assertFalse(first['completed'])
        self.assertEqual(len(first['created']), 1)
        self.assertEqual(p.advance(self.b, self.now.return_value)['created'], [])
        source_count = self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0]
        self.b.db.execute("UPDATE ct_activity_stage SET state='sealed',event=NULL WHERE project=? AND position=1", (self.pid,))
        self.b.db.commit()  # Simulate a lost receipt after canonical capture committed.
        self.assertEqual(p.advance(self.b, self.now.return_value)['created'], first['created'])
        self.assertEqual(source_count, self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0])
        self.now.return_value += 300
        done = p.advance(self.b, self.now.return_value)
        self.assertTrue(done['completed'])
        rows = list(self.b.db.execute('SELECT stage,origin,occurred FROM ct_life WHERE id<>? ORDER BY occurred', (self.pid,)))
        self.assertEqual([r['stage'] for r in rows], ['progress', 'completed'])
        self.assertTrue(all(r['origin'] == 'virtual' for r in rows))
        self.assertEqual(rows[-1]['occurred'], self.current['started_at'] + 600)
        count = self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0]
        self.assertEqual(p.advance(self.b, self.now.return_value)['created'], [])
        self.assertEqual(count, self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0])

    def test_unplanned_expiry_and_late_planning_cannot_claim_completed_work(self):
        self.now.return_value += 7200
        self.assertFalse(p.advance(self.b, self.now.return_value)['completed'])
        self.assertEqual(self.call('view')['project']['status'], 'awaiting_plan')
        self.assertFalse(self.call('artifact')['ready'])
        self.call('plan', expected_version=0, plan=self.plan())
        view = self.call('view')['project']
        self.assertEqual(view['visible_stages'], [])
        self.assertEqual(view['ends_at'], self.now.return_value + 600)
        self.assertFalse(self.call('artifact')['ready'])

    def test_artifact_requires_explicit_fetch_after_due_completion(self):
        self.call('plan', expected_version=0, plan=self.plan())
        self.assertFalse(self.call('artifact')['ready'])
        self.now.return_value += 600
        artifact = self.call('artifact')
        self.assertTrue(artifact['ready'])
        self.assertEqual(artifact['artifact'], self.plan()['artifact'])
        self.assertNotIn('NATIVE-ARTIFACT', json.dumps(self.call('view')))
        with self.assertRaises(ValueError):
            self.call('interrupt', expected_version=1)
        with self.assertRaises(ValueError):
            self.call('revise', expected_version=1, plan=self.plan())
        self.assertEqual(self.call('artifact')['artifact'], artifact['artifact'])

    def test_unplanned_activity_can_pause_without_inventing_a_result(self):
        self.assertEqual(self.call('interrupt', expected_version=0)['project']['status'], 'paused')
        self.now.return_value += 6000
        self.assertFalse(p.advance(self.b, self.now.return_value)['completed'])
        self.call('plan', expected_version=0, plan=self.plan())
        self.assertEqual(self.call('view')['project']['visible_stages'], [])

    def test_project_mutations_cannot_overlap_source_capture_commits(self):
        with p._lock(self.b), self.assertRaisesRegex(ValueError, 'activity_project_busy'):
            self.call('plan', expected_version=0, plan=self.plan())
        self.assertEqual(self.call('view')['project']['version'], 0)
        self.call('plan', expected_version=0, plan=self.plan())

    def test_pause_and_revision_preserve_revealed_past_and_original_drafts(self):
        original = self.plan()
        self.call('plan', expected_version=0, plan=original)
        self.now.return_value += 350
        paused = self.call('interrupt', expected_version=1, reason='先接主人一句话')
        self.assertEqual(paused['project']['status'], 'paused')
        self.now.return_value += 2000
        self.assertNotIn('SEALED-SECOND', json.dumps(self.call('view')))
        revision = self.plan()
        revision['topic'] = '修钟猫暂借一颗星'
        revision['stages'][0]['description'] = 'REVISED-FIRST 猫向星星借了一小束光。'
        revision['stages'][1]['description'] = 'REVISED-END 修好钟后，猫把星光原样归还。'
        revision['artifact']['text'] = 'REVISED-ARTIFACT 店门已经打开。猫借来星光修好了钟。'
        self.call('revise', expected_version=1, plan=revision)
        self.assertTrue(self.call('revise', expected_version=1, plan=revision)['replayed'])
        self.call('interrupt', expected_version=2)
        retry = self.call('revise', expected_version=1, plan=revision)
        self.assertTrue(retry['replayed'])
        self.assertEqual(retry['project']['status'], 'paused')
        self.call('revise', expected_version=2, plan=revision)
        self.assertIn('FIRST-VISIBLE', json.dumps(self.call('view')))
        self.assertNotIn('REVISED-FIRST', json.dumps(self.call('view')))
        self.now.return_value += 700
        p.advance(self.b, self.now.return_value)
        sources = '\n'.join(r[0] for r in self.b.db.execute('SELECT text FROM source_events'))
        self.assertNotIn('SEALED-SECOND', sources)
        self.assertIn('FIRST-VISIBLE', sources)
        self.assertIn('REVISED-END', sources)
        originals = [json.loads(r[0]) for r in self.b.db.execute('SELECT payload FROM ct_activity_plan WHERE project=? ORDER BY version', (self.pid,))]
        self.assertEqual(originals, [original, revision, revision])

    def test_plan_identity_numbers_versions_and_revision_gates(self):
        invalid = [dict(version=True), dict(origin='observed'), dict(activity='真实阅读')]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call('plan', expected_version=0, plan=dict(self.plan(), **changes))
        for offset in [True, float('nan'), float('inf'), -1, 0, 21601, 10**1000]:
            bad = copy.deepcopy(self.plan())
            bad['stages'][0]['after_seconds'] = offset
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.call('plan', expected_version=0, plan=bad)
        with self.assertRaises(ValueError):
            self.call('plan', expected_version=True, plan=self.plan())
        self.call('plan', expected_version=0, plan=self.plan())
        self.assertTrue(self.call('plan', expected_version=0, plan=self.plan())['replayed'])
        with self.assertRaises(ValueError):
            self.call('revise', expected_version=1, plan=self.plan())
        conflicting = self.plan()
        conflicting['topic'] = '改变已经接受的计划'
        with self.assertRaises(ValueError):
            self.call('plan', expected_version=0, plan=conflicting)
        with self.assertRaises(ValueError):
            p.register(self.b, dict(self.current, project_id=None, origin='observed'))
        with self.assertRaises(ValueError):
            p.register(self.b, dict(self.current, project_id=None, phone_intent='real-reading-intent'))


if __name__ == '__main__':
    unittest.main()
