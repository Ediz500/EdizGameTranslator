import base64
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from legacy_capture import LegacyObsSource as ObsSource
from PIL import Image


class OBSContractTests(unittest.TestCase):
    def test_obs_sdk_screenshot_contract_without_obs(self):
        buffer = io.BytesIO()
        Image.new('RGB', (80, 45), (5, 18, 52)).save(buffer, format='PNG')
        response = SimpleNamespace(image_data='data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode())
        fake_sdk = MagicMock()
        fake_sdk.ReqClient.return_value.get_source_screenshot.return_value = response
        with patch.dict(sys.modules, {'obsws_python': fake_sdk}):
            obs = ObsSource('secret-password', 4455)
            image = obs.frame('PS5 Capture')
            self.assertEqual(image.size, (80, 45))
            fake_sdk.ReqClient.return_value.get_source_screenshot.assert_called_once_with('PS5 Capture', 'png', 1920, 1080, -1)
            obs.client.get_input_list.return_value.inputs = [{'inputName': 'PS5 Capture'}, {'inputName': 'Mic'}]
            self.assertEqual(obs.list_inputs(), ['Mic', 'PS5 Capture'])


if __name__ == '__main__':
    unittest.main()
