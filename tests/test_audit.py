"""Settings and punctuation-preserving cache regressions."""
import importlib.util
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import BudgetLedger, ContextMemory, TranslationEngine, load_settings, save_settings


class AuditTests(unittest.TestCase):
    def test_settings_exclude_runtime_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('core.config_folder', return_value=Path(folder)):
                save_settings({'game': 'Test', 'api_key_runtime': 'dummy',
                               'obs_password_runtime': 'dummy'})
                saved = json.loads((Path(folder) / 'settings.json').read_text())
                self.assertEqual(saved, {'game': 'Test'})

    def test_valid_json_array_uses_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'settings.json').write_text('[]')
            with patch('core.config_folder', return_value=Path(folder)):
                self.assertEqual(load_settings()['obs_port'], 4455)

    def test_cache_preserves_meaningful_punctuation(self):
        memory = ContextMemory('Test', '')
        memory.remember('gpt-6.1-sol', "We're here.", 'Buradayız.')
        self.assertIsNone(memory.cached('gpt-6.1-sol', 'Were here?'))


if __name__ == '__main__':
    unittest.main()
