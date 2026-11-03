import tempfile
import time
import unittest
from memory_bridge.core import Policy,Store,Denied,Invalid
from memory_bridge.muse import ScopeGrant,row_digest,transform

def row(**changes):
    value={'scope':'owner-private','text':'Synthetic project uses SQLite.','kind':'fact','source':'synthetic-cli','event_id':'event-001','evidence':'confirmed','status':'active','importance':0.5,'occurred_at':1000,'created_at':1001,'supersedes':None,'fingerprint':'synthetic-fingerprint'}
    value.update(changes); return value

def convert(value,**changes):
    args=dict(grant=ScopeGrant('synthetic-owner','owner-private','owner','shared'),verified_principal='synthetic-owner',selected_digest=row_digest(value),category='project_fact',record_id='row-001'); args.update(changes)
    return transform(value,**args)

class MuseContract(unittest.TestCase):
    def test_confirmed_fact_candidate_requires_separate_core_consent(self):
        event=convert(row())
        with tempfile.TemporaryDirectory() as root:
            p=Policy('owner','shared'); s=Store(root,'owner',p)
            with self.assertRaises(Denied): s.ingest([event])
            p.approve(event,audience='shared',until=int(time.time())+100,consent=True); s.ingest([event,event])
            self.assertEqual(len(s.events()),1); self.assertEqual(len(s.query()),1); s.close()
    def test_reject_inferred_preferences_emotion_and_raw_fields(self):
        for changes in ({'evidence':'inference'},{'evidence':'observed'},{'kind':'preference'},{'kind':'reflection'},{'kind':'relation'},{'kind':'episode'},{'status':'deleted'}):
            with self.subTest(changes=changes),self.assertRaises(Denied): convert(row(**changes))
        for field in ('persona','emotion','original_event','actor','consent','system_prompt'):
            with self.subTest(field=field),self.assertRaises(Invalid): convert(row(**{field:'synthetic'}))
    def test_no_implicit_owner_private_or_group_sender_mapping(self):
        for scope in ('qq:group:synthetic-group','qq:c2c:synthetic-peer','unknown'):
            with self.assertRaises(Denied): convert(row(scope=scope))
        with self.assertRaises(Denied): convert(row(),verified_principal='untrusted-sender')
        with self.assertRaises(Denied): convert(row(),grant=None)
    def test_explicit_group_mapping_does_not_export_scope_or_sender(self):
        value=row(scope='qq:group:synthetic-group')
        event=convert(value,grant=ScopeGrant('synthetic-owner',value['scope'],'owner','shared'))
        self.assertNotIn('synthetic-group',str(event)); self.assertNotIn('synthetic-owner',str(event))
    def test_exact_selected_row_required(self):
        with self.assertRaises(Denied): convert(row(text='Changed'),selected_digest=row_digest(row()))
        with self.assertRaises(Denied): convert(row(),selected_digest=None)
    def test_source_namespaces_prevent_cross_source_collisions(self):
        a=convert(row()); b=convert(row(source='other-adapter'))
        self.assertNotEqual(a['source'],b['source']); self.assertNotEqual(a['id'],b['id']); self.assertNotEqual(a['fact'],b['fact'])
        self.assertEqual(a,convert(row()))
    def test_same_identity_changed_text_is_core_conflict(self):
        a=convert(row()); b=convert(row(text='Different project fact'))
        self.assertEqual(a['fact'],b['fact']); self.assertNotEqual(a['id'],b['id'])
        with tempfile.TemporaryDirectory() as root:
            p=Policy('owner','shared'); s=Store(root,'owner',p)
            for e in (a,b): p.approve(e,audience='shared',until=int(time.time())+100,consent=True)
            s.ingest([a,b]); self.assertEqual(s.query(),[]); self.assertEqual(len(s.conflicts()),1); s.close()
    def test_reject_supersession_unknown_shape_badtime_secret(self):
        for changes in ({'supersedes':'prior-row'},{'occurred_at':'yesterday'},{'text':'persona=synthetic secret'},{'importance':True},{'event_id':''}):
            with self.subTest(changes=changes),self.assertRaises(Invalid): convert(row(**changes))
        with self.assertRaises(Denied): convert(row(),category='preference')
    def test_size_bound(self):
        with self.assertRaises(Invalid): convert(row(text='x'*65537))


class MuseAPIContract(unittest.TestCase):
    def selected(self,**changes):
        r={'id':1,'text':'Synthetic project fact','kind':'fact','source':'synthetic-source','event_id':'same-event','evidence':'confirmed','occurred_at':1000.75,'truncated':False}; r.update(changes); return r
    def call(self,r,**changes):
        from memory_bridge.muse import api_row_digest,transform_response
        args=dict(origin='recall',selected_row_id=r['id'],selected_digest=api_row_digest(r),grant=ScopeGrant('synthetic-owner','owner-private','owner','shared'),verified_principal='synthetic-owner',category='project_fact'); args.update(changes)
        return transform_response({'memories':[r],'mood':object(),'emotion':object(),'style':object(),'event':object()},**args)
    def test_real_api_shape_fractional_seconds_and_ignored_envelope(self):
        a=self.call(self.selected()); self.assertEqual(a['timestamp'],1000)
        self.assertEqual(a,self.call(self.selected(),origin='prepare'))
    def test_two_rows_same_event_stay_distinct(self):
        a=self.call(self.selected()); b=self.call(self.selected(id=2,text='Second independent fact'))
        self.assertNotEqual(a['fact'],b['fact'])
    def test_bad_origin_sender_truncation_inference(self):
        for args in ({'origin':'events'},{'verified_principal':'other'},{'grant':None}):
            with self.subTest(args=args),self.assertRaises(Invalid): self.call(self.selected(),**args)
        for values in ({'truncated':True},{'evidence':'inference'},{'kind':'preference'},{'occurred_at':float('nan')},{'occurred_at':10**500}):
            with self.subTest(values=values),self.assertRaises(Invalid): self.call(self.selected(**values))
    def test_merged_unknown_fields_rejected(self):
        with self.assertRaises(Invalid): self.call(self.selected(merge_group='x',original_ids=[1,2]))
