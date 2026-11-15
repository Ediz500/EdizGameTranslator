import base64
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import BudgetLedger, ContextMemory, TranslationEngine
from legacy_capture import LegacyObsSource as ObsSource
from PIL import Image


class APIContractTests(unittest.TestCase):
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

    def test_openai_api_contract_without_spending(self):
        fake_sdk = MagicMock()
        returned = SimpleNamespace(output_text='Dikkat et, geliyorlar!',
                                   usage=SimpleNamespace(input_tokens=120, output_tokens=15))
        fake_sdk.OpenAI.return_value.responses.create.return_value = returned
        mem = ContextMemory('Test game', 'Ali bir karakter')
        ledger = BudgetLedger(0, 50, 5000)
        with patch.dict(sys.modules, {'openai': fake_sdk}):
            engine = TranslationEngine('api-key-not-real', 'gpt-6.1-sol', mem, ledger)
            result, detail = engine.translate("Watch out, they're coming!")
        self.assertEqual(result, 'Dikkat et, geliyorlar!')
        self.assertGreater(detail.usd, 0)
        kwargs = fake_sdk.OpenAI.return_value.responses.create.call_args.kwargs
        self.assertEqual(kwargs['model'], 'gpt-6.1-sol')
        self.assertEqual(kwargs['store'], False)
        self.assertIn('Test game', kwargs['input'])
        self.assertTrue(ledger.spent_try() > 0)


if __name__ == '__main__':
    unittest.main()
