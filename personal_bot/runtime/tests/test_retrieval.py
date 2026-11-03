import tempfile,unittest,json,hashlib
from unittest.mock import patch
from brain import Brain

class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.b=Brain(self.tmp.name)
        self.b.dispatch(dict(op='configure',enabled=True,features={'vector':True}))
    def tearDown(self):self.b.close();self.tmp.cleanup()
    def add(self,text,**kw):
        q=dict(op='remember',scope='owner-private',text=text,event_id=text,source='fixture:user',entities=[]);q.update(kw)
        return self.b.dispatch(q)['id']
    def test_semantic_old_memory_not_limited_to_latest300(self):
        from muse_ext.embeddings import store_vector,MODEL_ID
        old=self.add('我的通勤工具是脚踏车',occurred_at=1)
        store_vector(self.b,old,[1.,0.],MODEL_ID)
        for i in range(310):self.add('无关的旅行记录'+str(i))
        with patch('muse_ext.embeddings.encode',return_value=[1.,0.]):
            r=self.b.dispatch(dict(op='recall',scope='owner-private',text='你骑什么去上班'))
        self.assertEqual(r['memories'][0]['id'],old);self.assertTrue(r['vector'])
    def test_stale_vectors_and_other_scope_cannot_leak(self):
        from muse_ext.embeddings import store_vector,MODEL_ID
        a=self.add('脚踏车');secret=self.add('秘密脚踏车',scope='qq:group:A')
        store_vector(self.b,a,[1.,0.],MODEL_ID);store_vector(self.b,secret,[1.,0.],MODEL_ID)
        self.b.dispatch(dict(op='forget',scope='owner-private',id=a))
        with patch('muse_ext.embeddings.encode',return_value=[1.,0.]):
            r=self.b.dispatch(dict(op='recall',scope='owner-private',text='骑车上班'))
        self.assertEqual(r['memories'],[])
    def test_model_outage_explicit_keyword_fallback(self):
        self.add('蓝鲸青柠')
        with patch('muse_ext.embeddings.encode',side_effect=TimeoutError):
            r=self.b.dispatch(dict(op='recall',scope='owner-private',text='蓝鲸'))
        self.assertEqual(len(r['memories']),1);self.assertFalse(r['vector'])
        self.assertEqual(r['vector_status'],'unavailable_keyword_fallback')
    def test_graph_neighbor_expansion_is_scope_limited(self):
        a=self.add('王老师指导了课程',entities=['王老师','机器学习'])
        b=self.add('课程将在周末讨论',entities=['机器学习'])
        self.add('隐藏课程',scope='qq:group:X',entities=['机器学习'])
        with patch('muse_ext.embeddings.encode',side_effect=TimeoutError):
            r=self.b.dispatch(dict(op='recall',scope='owner-private',text='王老师'))
        self.assertEqual({x['id'] for x in r['memories']},{a,b})
        self.assertTrue(r['graph'])
    def test_real_vector_dimension_and_hash_validation(self):
        from muse_ext.embeddings import store_vector,MODEL_ID
        a=self.add('脚踏车')
        with self.assertRaises(ValueError):store_vector(self.b,a,[float('nan')],MODEL_ID)
        store_vector(self.b,a,[1.,0.],MODEL_ID)
        self.b.db.execute('UPDATE memories SET fingerprint=? WHERE id=?',('stale',a));self.b.db.commit()
        with patch('muse_ext.embeddings.encode',return_value=[1.,0.]):
            r=self.b.dispatch(dict(op='recall',scope='owner-private',text='通勤交通'))
        self.assertEqual(r['memories'],[])

    def test_semantic_budget_exhaustion_discards_partial_rank_and_falls_back(self):
        from muse_ext.embeddings import store_vector,MODEL_ID
        a=self.add('骑自行车');store_vector(self.b,a,[1.,0.],MODEL_ID)
        with patch('muse_ext.embeddings.encode',return_value=[1.,0.]),patch('muse_ext.retrieval.time.perf_counter',side_effect=[0.,1.]):
            r=self.b.dispatch(dict(op='recall',scope='owner-private',text='通勤工具'))
        self.assertFalse(r['vector']);self.assertEqual(r['vector_status'],'budget_exceeded_keyword_fallback')
        self.assertEqual(r['memories'],[])
