import concurrent.futures
import tempfile
import threading
import unittest
import json
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
from brain import Brain, config_guard, atomic_json
from ops import rollback,snapshot


class ConcurrencyTests(unittest.TestCase):
    def test_pause_between_initial_check_and_send_gate_blocks_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Brain(tmp)
            b.dispatch(dict(op='configure',enabled=True))
            mid=b.dispatch(dict(op='remember',scope='owner-private',text='事实鲸鱼',source='fixture:u',event_id='old'))['id']
            b.dispatch(dict(op='life',scope='owner-private',text='分析',sources=[mid],topic='one'))
            c=b.dispatch(dict(op='claim',scope='owner-private'))['candidate']
            @contextmanager
            def paused_guard(root):
                with config_guard(root):
                    cfg=b.config();cfg['modules']['life']=False
                    atomic_json(b.config_path,cfg)
                    yield
            try:
                with patch('brain.config_guard',paused_guard):
                    r=b.dispatch(dict(op='authorize',scope='owner-private',id=c['id'],lease=c['lease'],epoch=c['epoch']))
                self.assertFalse(r['ok'])
            finally:
                b.close()
    def test_concurrent_corrections_leave_one_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Brain(tmp)
            b.dispatch(dict(op='configure',enabled=True))
            mid=b.dispatch(dict(op='remember',scope='owner-private',text='原始鲸鱼',source='fixture:u',event_id='old'))['id']
            gate=threading.Barrier(2)
            def change(i):
                other=Brain(tmp)
                gate.wait()
                try:
                    return other.dispatch(dict(op='correct',scope='owner-private',id=mid,text='新鲸鱼'+str(i),source='fixture:u',event_id=str(i)))['ok']
                except (ValueError, __import__('sqlite3').OperationalError):
                    return False
                finally:
                    other.close()
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results=list(pool.map(change,[1,2]))
            self.assertEqual(sum(results),1)
            self.assertEqual(b.db.execute("select count(*) from memories where status='active'").fetchone()[0],1)
            b.close()

    def test_module_update_cannot_reenable_after_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Brain(tmp)
            b.dispatch(dict(op='configure',enabled=True))
            m=snapshot(tmp,[])
            gate=threading.Barrier(5)
            def change(i):
                other=Brain(tmp)
                gate.wait()
                try:
                    if i==0:
                        return rollback(tmp,m)
                    return other.dispatch(dict(op='configure',modules={'style':bool(i%2)}))
                finally:
                    other.close()
            with concurrent.futures.ThreadPoolExecutor(5) as pool:
                list(pool.map(change,range(5)))
            self.assertFalse(b.config()['enabled'])
            self.assertGreaterEqual(b.config()['epoch'],2)
            b.close()

    def test_finish_source_check_holds_write_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Brain(tmp)
            b.dispatch(dict(op='configure',enabled=True))
            mid=b.dispatch(dict(op='remember',scope='owner-private',text='旧鲸鱼',source='fixture:u',event_id='old'))['id']
            b.dispatch(dict(op='life',scope='owner-private',text='旧分析',sources=[mid],topic='one'))
            c=b.dispatch(dict(op='claim',scope='owner-private'))['candidate']
            checked=threading.Event()
            finished=threading.Event()
            results=[]
            def correction():
                other=Brain(tmp)
                checked.wait(3)
                try:
                    other.dispatch(dict(op='correct',scope='owner-private',id=mid,text='新鲸鱼',source='fixture:u',event_id='new'))
                    results.append(True)
                except __import__('sqlite3').OperationalError:
                    results.append(False)
                finally:
                    other.close(); finished.set()
            worker=threading.Thread(target=correction)
            worker.start()
            original=b.valid_sources
            def held(row):
                result=original(row)
                checked.set()
                self.assertTrue(finished.wait(3))
                return result
            b.valid_sources=held
            b.dispatch(dict(op='finish',scope='owner-private',id=c['id'],lease=c['lease'],epoch=c['epoch'],outcome='accepted'))
            worker.join(3)
            b.close()
            self.assertEqual(results,[False])
