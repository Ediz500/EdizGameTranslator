from bootstrap import configure_paths
configure_paths()
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock
from ediz_game_translator.capture.virtual_camera import VirtualCamera,CaptureConfigurationError


def collection(source='Raw'):
    return dict(name='Test',**{'virtual-camera':dict(type2=2,source=source)},
        sources=[dict(name='Raw',id='dshow_input',settings=dict(video_device_id='card'),filters=[])])


class GuardCostsTests(unittest.TestCase):
    def test_config_cache_still_checks_live_route_every_time_and_reloads_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'collection.json';p.write_text(json.dumps(collection()))
            camera=VirtualCamera.__new__(VirtualCamera);camera.path=p;camera.source='Raw'
            camera._config_signature=None;camera._config_data=None;camera.validator=MagicMock()
            a=camera._check();b=camera._check()
            self.assertTrue(a['config_reread']);self.assertFalse(b['config_reread'])
            self.assertEqual(camera.validator.call_count,2)
            p.write_text(json.dumps(collection('Bad route')))
            with self.assertRaises(CaptureConfigurationError):camera._check()

    def test_live_failure_does_not_use_cached_success(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'collection.json';p.write_text(json.dumps(collection()))
            c=VirtualCamera.__new__(VirtualCamera);c.path=p;c.source='Raw'
            c._config_signature=None;c._config_data=None;c.validator=MagicMock()
            c._check();c.validator.side_effect=CaptureConfigurationError('route lost')
            with self.assertRaises(CaptureConfigurationError):c._check()
