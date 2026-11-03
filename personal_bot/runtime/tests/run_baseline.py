"""Run exported function tests and legacy unittest cases on synthetic fixtures.

The legacy suite predates mandatory proactive policy. Only its environment is
seeded; assertions and production gates remain unchanged. Per-test mocked clocks
override the daytime default. Explicit malformed policies are not replaced.
"""
import importlib
import inspect
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
import brain
import proactive
from support import seed_legacy_policy


def main():
    originals = brain.Brain.__init__

    def synthetic_init(self, root):
        originals(self, root)
        seed_legacy_policy(root)

    legacy = unittest.TestSuite()
    suite = unittest.TestSuite()
    names = sys.argv[1:] or ['test_brain', 'test_concurrency', 'test_ops',
                            'test_proactive', 'test_news_dispatch', 'test_heartbeat_digest']
    for name in names:
        module = importlib.import_module(name)
        target = legacy if name in ('test_brain', 'test_concurrency', 'test_ops') else suite
        target.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
        for key, fn in inspect.getmembers(module, inspect.isfunction):
            if key.startswith('test_') and fn.__module__ == module.__name__:
                suite.addTest(unittest.FunctionTestCase(fn, description=name+'.'+key))
    daytime = datetime(2026, 11, 3, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    with mock.patch.object(proactive, 'beijing_now', return_value=daytime):
        with mock.patch.object(brain.Brain, '__init__', synthetic_init):
            old_result = unittest.TextTestRunner(verbosity=2).run(legacy)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    print('TOTAL', old_result.testsRun + result.testsRun)
    return 0 if old_result.wasSuccessful() and result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
