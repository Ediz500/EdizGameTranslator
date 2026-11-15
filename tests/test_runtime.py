import unittest
from unittest.mock import patch
import runtime_check


class RuntimeTests(unittest.TestCase):
    def test_supported_windows(self):
        with patch.object(runtime_check.sys, 'platform', 'win32'), patch.object(runtime_check.sys, 'version_info', (3, 12)), patch('runtime_check.platform.python_implementation', return_value='CPython'), patch('runtime_check.struct.calcsize', return_value=8), patch('runtime_check.sysconfig.get_platform', return_value='win-amd64'):
            self.assertTrue(runtime_check.supported())

    def test_msys_wrong_version_and_arch_rejected(self):
        with patch('runtime_check.sysconfig.get_platform', return_value='mingw_x86_64'):
            self.assertFalse(runtime_check.supported())
        with patch.object(runtime_check.sys, 'version_info', (3, 11)):
            self.assertFalse(runtime_check.supported())
        with patch('runtime_check.struct.calcsize', return_value=4):
            self.assertFalse(runtime_check.supported())
