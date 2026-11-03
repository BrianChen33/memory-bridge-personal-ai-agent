import tempfile,unittest,json
from pathlib import Path
from brain import Brain

class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.b=Brain(self.t.name)
        self.b.dispatch(dict(op='configure',enabled=True,features={'reading':True}))
        (self.b.root/'library').mkdir();self.path=self.b.root/'library'/'public.md'
        self.path.write_text('SQLite在线备份可以在数据库运行时生成一致的数据库副本。'+('示例说明。'*600),encoding='utf-8')
        self.registry={'version':1,'documents':[{'id':'sqlite-backup','path':'library/public.md','source_url':'https://www.sqlite.org/backup.html','public':True}]}
        (self.b.root/'reading-sources.json').write_text(json.dumps(self.registry),encoding='utf-8')
    def tearDown(self):self.b.close();self.t.cleanup()
    def call(self,action,**kw):return self.b.dispatch(dict(op='reading',action=action,scope='owner-private',**kw))
    def test_claim_commit_real_quote_inference_and_cursor(self):
        c=self.call('claim')['chunk'];self.assertEqual(c['start'],0)
        r=self.call('commit',chunk_id=c['id'],lease=c['lease'],summary='在线备份适合正在运行的数据库。')
        self.assertTrue(r['ok'])
        self.assertEqual(self.b.db.execute('SELECT cursor FROM reading_documents').fetchone()[0],c['end'])
        notes=self.b.db.execute('SELECT * FROM memories ORDER BY id').fetchall()
        self.assertEqual(notes[0]['evidence'],'observed');self.assertEqual(notes[0]['text'],c['text'])
        self.assertEqual(notes[1]['evidence'],'inference');self.assertEqual(notes[1]['kind'],'reflection')
        found=self.b.dispatch(dict(op='recall',scope='owner-private',text='SQLite在线备份'))
        self.assertTrue(found['memories'])
    def test_failed_note_does_not_advance_and_retry_is_idempotent(self):
        c=self.call('claim')['chunk']
        with self.assertRaises(ValueError):self.call('commit',chunk_id=c['id'],lease=c['lease'],summary='')
        self.assertEqual(self.b.db.execute('SELECT cursor FROM reading_documents').fetchone()[0],0)
        self.call('commit',chunk_id=c['id'],lease=c['lease'],summary='这是来源支持的学习总结。')
        count=self.b.db.execute('SELECT COUNT(*) FROM memories').fetchone()[0]
        self.call('commit',chunk_id=c['id'],lease=c['lease'],summary='这是来源支持的学习总结。')
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM memories').fetchone()[0],count)
    def test_source_changed_before_commit_refused(self):
        c=self.call('claim')['chunk'];self.path.write_text('源文档已经改变',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'source_changed'):
            self.call('commit',chunk_id=c['id'],lease=c['lease'],summary='旧源摘要不能继续提交')
        self.assertEqual(self.b.db.execute('SELECT cursor FROM reading_documents').fetchone()[0],0)
    def test_chunk_claim_lease_prevents_duplicate_reader(self):
        c=self.call('claim')['chunk'];other=self.call('claim')
        self.assertIsNone(other['chunk'])
        with self.assertRaisesRegex(ValueError,'invalid_reading_lease'):
            self.call('commit',chunk_id=c['id'],lease='wrong',summary='这段摘要没有正确租约')
    def test_registry_rejects_path_escape_and_private_scope(self):
        self.registry['documents'][0]['path']='../MEMORY.md'
        (self.b.root/'reading-sources.json').write_text(json.dumps(self.registry))
        with self.assertRaisesRegex(ValueError,'unsafe_reading_path'):self.call('claim')
        with self.assertRaisesRegex(ValueError,'reading_owner_only'):
            self.b.dispatch(dict(op='reading',action='claim',scope='qq:group:A'))
    def test_quote_must_equal_claimed_source_and_source_link_is_retained(self):
        c=self.call('claim')['chunk']
        self.call('commit',chunk_id=c['id'],lease=c['lease'],summary='这份说明介绍在线备份的一致性。')
        r=self.b.db.execute('SELECT * FROM reading_chunks').fetchone()
        self.assertEqual(r['source_hash'],c['source_hash'])
        self.assertEqual(r['source_url'],'https://www.sqlite.org/backup.html')
