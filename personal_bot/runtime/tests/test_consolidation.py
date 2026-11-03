import tempfile,unittest
from brain import Brain

class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.b=Brain(self.t.name)
        self.b.dispatch(dict(op='configure',enabled=True,features={'consolidation':True}))
    def tearDown(self):self.b.close();self.t.cleanup()
    def add(self,text,**kw):
        q=dict(op='remember',scope='owner-private',text=text,source='fixture:user',event_id=text,kind='fact');q.update(kw)
        return self.b.dispatch(q)['id']
    def call(self,action,**kw):return self.b.dispatch(dict(op='consolidate',action=action,scope='owner-private',**kw))
    def assessment(self,ids):
        rows=[self.b.db.execute('SELECT * FROM memories WHERE id=?',(i,)).fetchone() for i in ids]
        return dict(ids=ids,hashes={str(r['id']):r['fingerprint'] for r in rows},relation='equivalent',reason='相同主体和时间的相同偏好，两句语义等价',quotes={str(r['id']):r['text'] for r in rows})
    def test_merge_preserves_originals_collapses_recall_and_undo(self):
        a=self.add('我通勤骑自行车');b=self.add('我上班骑自行车')
        merged=self.call('merge',**self.assessment([a,b]))
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM memories').fetchone()[0],2)
        r=self.b.dispatch(dict(op='recall',scope='owner-private',text='自行车'))
        self.assertEqual(len(r['memories']),1);self.assertEqual(len(r['memories'][0]['original_ids']),2)
        self.call('undo',id=merged['id'])
        self.assertEqual(len(self.b.dispatch(dict(op='recall',scope='owner-private',text='自行车'))['memories']),2)
    def test_no_cosine_only_merge_or_cross_scope(self):
        a=self.add('喜欢苹果');b=self.add('喜欢苹果',scope='qq:group:A')
        with self.assertRaises(ValueError):self.call('merge',ids=[a,b],similarity=.99)
        with self.assertRaisesRegex(ValueError,'same_scope'):
            self.call('merge',**self.assessment([a,b]))
    def test_changed_numbers_negation_go_to_conflict(self):
        a=self.add('周五下午3点开会');b=self.add('周五下午4点开会')
        r=self.call('merge',**self.assessment([a,b]))
        self.assertEqual(r['status'],'conflict');self.assertFalse(r['merged'])
        c=self.add('我不喜欢咖啡');d=self.add('我喜欢咖啡')
        self.assertEqual(self.call('merge',**self.assessment([c,d]))['status'],'conflict')
    def test_stale_source_hash_refused(self):
        a=self.add('通勤骑车');b=self.add('上班骑车');q=self.assessment([a,b]);q['hashes'][str(a)]='wrong'
        with self.assertRaisesRegex(ValueError,'stale_source'):self.call('merge',**q)
    def test_forgotten_alias_cannot_reappear_even_after_undo(self):
        a=self.add('通勤骑自行车');b=self.add('上班骑自行车');r=self.call('merge',**self.assessment([a,b]))
        self.b.dispatch(dict(op='forget',scope='owner-private',id=a))
        self.call('undo',id=r['id'])
        self.assertEqual(self.b.dispatch(dict(op='recall',scope='owner-private',text='自行车'))['memories'],[])
    def test_corrected_group_does_not_return_old_alias(self):
        a=self.add('喜欢蓝色');b=self.add('我喜欢蓝色');self.call('merge',**self.assessment([a,b]))
        self.b.dispatch(dict(op='correct',scope='owner-private',id=a,text='喜欢绿色',source='fixture:user',event_id='correct'))
        r=self.b.dispatch(dict(op='recall',scope='owner-private',text='喜欢'))
        self.assertEqual([x['text'] for x in r['memories']],['喜欢绿色'])
    def test_incompatible_kind_or_evidence_refused(self):
        a=self.add('喜欢苹果');b=self.add('喜欢苹果',kind='reflection',evidence='inference',event_id='inference')
        with self.assertRaisesRegex(ValueError,'incompatible'):self.call('merge',**self.assessment([a,b]))
