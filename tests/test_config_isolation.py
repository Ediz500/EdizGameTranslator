from bootstrap import configure_paths
configure_paths()
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ediz_game_translator.core import config_folder,load_settings,save_settings


class ConfigIsolationTests(unittest.TestCase):
    def test_opt_in_profile_preserves_legacy_values_and_ledger(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'EDIZ_CONFIG_DIR':folder}):
            path=Path(folder)
            self.assertEqual(config_folder(),path.resolve())
            legacy=dict(model='gpt-6-luna',budget_try=1234,estimated_total_usd=12.3,
                        token_total_in=123,token_total_out=45,game='Test')
            (path/'settings.json').write_text(json.dumps(legacy))
            (path/'ledger.json').write_text('{"usd":12.3}')
            settings=load_settings();save_settings(settings)
            self.assertEqual(load_settings()['game'],'Test')
            for k in legacy.keys()-{'game'}:self.assertNotIn(k,load_settings())
            saved=json.loads((path/'settings.json').read_text())
            for k in legacy.keys()-{'game'}:self.assertNotIn(k,saved)
            self.assertEqual((path/'ledger.json').read_text(),'{"usd":12.3}')
            self.assertEqual(settings['translation_engine'],'ct2-marian')
            self.assertEqual(settings['local_model_path'],'')
