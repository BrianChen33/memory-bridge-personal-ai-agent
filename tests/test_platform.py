import unittest,tempfile,os
from unittest.mock import patch
from memory_bridge import core

class PlatformTests(unittest.TestCase):
    def test_windows_without_fchmod_can_open_local_store(self):
        class WindowsOS:
            name='nt'
            def __getattr__(self,name):
                if name=='fchmod':raise AssertionError('fchmod unavailable on older Windows Python')
                return getattr(os,name)
        with tempfile.TemporaryDirectory() as root,patch.object(core,'os',WindowsOS()):
            store=core.Store(root,'owner',core.Policy('owner','shared'));store.close()
