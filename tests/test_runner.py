import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from memory_bridge.runner import RunnerFailure,_read_input,run

class RunnerTests(unittest.TestCase):
    def test_self_test_structured_synthetic_only(self):
        result=run(io.BytesIO(b'{"mode":"self-test"}\n'))
        self.assertEqual(result['status'],'passed'); self.assertFalse(result['network_used']); self.assertFalse(result['production_data_accessed']); self.assertFalse(result['native_bots_invoked']); self.assertEqual(result['check_count'],7)
    def test_input_limits_invalid_json_and_unknown_fields(self):
        for raw in (b'x'*65537,b'{bad}',b'{"mode":"live"}',b'{"mode":"self-test","path":"/production"}',b'{"mode":"self-test","command":"echo secret"}',b'{"mode":"self-test","mode":"self-test"}',b'[]',b'{"mode":null}',b'\xff',b'{"mode":"self-test"}\n{"mode":"self-test"}'):
            with self.subTest(raw=raw[:40]),self.assertRaises(RunnerFailure): _read_input(io.BytesIO(raw),1)
    def test_no_arguments_and_no_error_echo(self):
        child=subprocess.run([sys.executable,'-m','memory_bridge.runner','/arbitrary-path'],input=b'{"mode":"self-test"}\n',capture_output=True,timeout=10)
        self.assertNotEqual(child.returncode,0); result=json.loads(child.stdout); self.assertEqual(result['error'],'unsupported_request'); self.assertNotIn(b'arbitrary-path',child.stdout); self.assertEqual(child.stderr,b'')
    def test_protocol_failure_exit_status(self):
        child=subprocess.run([sys.executable,'-m','memory_bridge.runner'],input=b'{"mode":"secret-invalid-mode"}\n',capture_output=True,timeout=10)
        self.assertNotEqual(child.returncode,0); self.assertEqual(json.loads(child.stdout)['error'],'unsupported_request'); self.assertNotIn(b'secret-invalid-mode',child.stdout)
    def test_worker_timeout_kills_and_cleans_scoped_directory(self):
        observed=[]; real=tempfile.TemporaryDirectory
        def tracked(*args,**kwargs):
            obj=real(*args,**kwargs); observed.append(Path(obj.name)); return obj
        started=time.monotonic()
        with patch('memory_bridge.runner.tempfile.TemporaryDirectory',side_effect=tracked):
            with self.assertRaisesRegex(RunnerFailure,'timeout'): run(io.BytesIO(b'{"mode":"self-test"}\n'),timeout=.1,test_delay=10)
        self.assertLess(time.monotonic()-started,3); self.assertEqual(len(observed),1); self.assertFalse(observed[0].exists())
    def test_blocked_input_is_bounded(self):
        release=threading.Event()
        class Blocked:
            def read(self,n): release.wait(1); return b''
        started=time.monotonic()
        try:
            with self.assertRaisesRegex(RunnerFailure,'timeout'): _read_input(Blocked(),.02)
            self.assertLess(time.monotonic()-started,.5)
        finally: release.set()
    def test_success_cleans_scoped_directory(self):
        observed=[]; real=tempfile.TemporaryDirectory
        def tracked(*args,**kwargs):
            obj=real(*args,**kwargs); observed.append(Path(obj.name)); return obj
        with patch('memory_bridge.runner.tempfile.TemporaryDirectory',side_effect=tracked): run(io.BytesIO(b'{"mode":"self-test"}\n'))
        self.assertEqual(len(observed),1); self.assertFalse(observed[0].exists())

    def test_open_stdin_timeout_exits_cleanly_without_buffered_lock_abort(self):
        script="import memory_bridge.runner as r; original=r.run; r.run=lambda stream: original(stream,timeout=.1); raise SystemExit(r.main())"
        child=subprocess.Popen([sys.executable,'-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            child.wait(timeout=3)
            output=child.stdout.read(); errors=child.stderr.read()
            self.assertEqual(child.returncode,1); self.assertEqual(json.loads(output)['error'],'timeout'); self.assertEqual(errors,b'')
        finally:
            if child.poll() is None: child.kill(); child.wait()
            child.stdin.close(); child.stdout.close(); child.stderr.close()
