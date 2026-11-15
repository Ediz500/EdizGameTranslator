"""P1 regressions; all API calls are mocks."""
import importlib.util
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import BudgetLedger, ContextMemory, TranslationEngine


class BudgetTests(unittest.TestCase):
    def test_legacy_token_totals_migrated(self):
        ledger = BudgetLedger(.1, 1, 10, initial_in=12, initial_out=3)
        ledger.record('gpt-6.1-sol', 2, 1)
        snapshot = ledger.snapshot()
        self.assertEqual(snapshot['input_tokens'], 14)
        self.assertEqual(snapshot['output_tokens'], 4)

    def test_disk_failure_prevents_network(self):
        ledger = BudgetLedger(0, 1, 10)
        sdk = MagicMock()
        with patch.dict(sys.modules, {'openai': sdk}), patch.object(ledger, '_persist', side_effect=OSError('disk full')):
            engine = TranslationEngine('dummy', 'gpt-6.1-sol', ContextMemory('', ''), ledger)
            with self.assertRaises(RuntimeError):
                engine.translate('Hello')
        sdk.OpenAI.return_value.responses.create.assert_not_called()
        self.assertFalse(ledger.can_spend())

    def test_failed_settlement_write_leaves_disk_reservation_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.json'
            ledger = BudgetLedger(0, 1, 10, path=path)
            token = ledger.reserve(.05)
            with patch('core.atomic_json', side_effect=OSError('disk full')):
                with self.assertRaises(RuntimeError):
                    ledger.settle(token, 'gpt-6.1-sol', 100, 10)
            self.assertFalse(ledger.can_spend())
            restored = BudgetLedger(0, 1, 10, path=path)
            self.assertFalse(restored.can_spend())
            self.assertAlmostEqual(restored.usd, .05)

    def test_timeout_keeps_reservation_and_disables_retry(self):
        ledger = BudgetLedger(0, 1, 10)
        sdk = MagicMock()
        sdk.OpenAI.return_value.responses.create.side_effect = TimeoutError('dummy-secret')
        with patch.dict(sys.modules, {'openai': sdk}):
            engine = TranslationEngine('dummy', 'gpt-6.1-sol', ContextMemory('', ''), ledger)
            with self.assertRaises(RuntimeError) as error:
                engine.translate('Hello')
        self.assertNotIn('dummy-secret', str(error.exception))
        self.assertEqual(sdk.OpenAI.call_args.kwargs['max_retries'], 0)
        self.assertAlmostEqual(ledger.usd, .05)
        self.assertFalse(ledger.can_spend())

    def test_oversized_input_rejected_before_api(self):
        sdk = MagicMock()
        with patch.dict(sys.modules, {'openai': sdk}):
            engine = TranslationEngine('dummy', 'gpt-6.1-sol', ContextMemory('', ''), BudgetLedger(0, 1, 10))
            with self.assertRaises(ValueError):
                engine.translate('x' * 361)
        sdk.OpenAI.return_value.responses.create.assert_not_called()

    def test_atomic_reservation(self):
        ledger = BudgetLedger(0, 1, .05)
        held = threading.Event()
        release = threading.Event()
        sdk = MagicMock()
        def response(**kw):
            held.set()
            release.wait(3)
            return SimpleNamespace(output_text='Test', usage=SimpleNamespace(input_tokens=100, output_tokens=10))
        sdk.OpenAI.return_value.responses.create.side_effect = response
        with patch.dict(sys.modules, {'openai': sdk}):
            engine = TranslationEngine('dummy', 'gpt-6.1-sol', ContextMemory('Test', ''), ledger)
            worker = threading.Thread(target=lambda: engine.translate('Hello'))
            worker.start()
            try:
                self.assertTrue(held.wait(2))
                with self.assertRaises(RuntimeError):
                    engine.translate('Other')
                self.assertEqual(sdk.OpenAI.return_value.responses.create.call_count, 1)
            finally:
                release.set()
                worker.join(4)

    def test_unknown_usage_blocks_more_requests_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.json'
            ledger = BudgetLedger(0, 1, 10, path=path)
            sdk = MagicMock()
            sdk.OpenAI.return_value.responses.create.return_value = SimpleNamespace(output_text='Test', usage=None)
            with patch.dict(sys.modules, {'openai': sdk}):
                engine = TranslationEngine('dummy', 'gpt-6.1-sol', ContextMemory('', ''), ledger)
                with self.assertRaises(RuntimeError):
                    engine.translate('Hello')
            self.assertFalse(ledger.can_spend())
            self.assertGreater(ledger.usd, 0)
            self.assertFalse(BudgetLedger(0, 1, 10, path=path).can_spend())

    def test_reservation_persisted_before_network_and_settlement_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.json'
            ledger = BudgetLedger(0, 1, 10, path=path)
            token = ledger.reserve(.05)
            self.assertFalse(BudgetLedger(0, 1, 10, path=path).can_spend())
            ledger.settle(token, 'gpt-6.1-sol', 100, 10)
            restored = BudgetLedger(0, 1, 10, path=path)
            self.assertAlmostEqual(restored.usd, .0003)
            self.assertTrue(restored.can_spend())

    def test_nonfinite_values_rejected(self):
        for value in (float('nan'), float('inf'), -1):
            with self.assertRaises(ValueError):
                BudgetLedger(0, value, 10)


class SessionTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('p1_app', Path(__file__).resolve().parents[1] / 'app.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'obs_capture': MagicMock()}):
            spec.loader.exec_module(self.module)
        self.window = self.module.MainWindow.__new__(self.module.MainWindow)
        w = self.window
        w.session_id = 2
        w.closing = False
        w.running = True
        w.subtitle_store = None
        w.latest_seq = 4
        w.events = queue.Queue()
        w.root = MagicMock()
        w.log = MagicMock()
        w.status_var = MagicMock()
        w.cost_var = MagicMock()
        w.overlay = MagicMock()
        w.overlay.enabled=False
        w.overlay_state = MagicMock()
        w.overlay_state.snapshot.return_value=dict(blocks=[],waiting=0,backlog_seconds=0,translation_pending=0,overloaded=False)
        w.last_translation_var=MagicMock();w.connection_var=MagicMock()
        w.ledger = BudgetLedger(0, 1, 10)
        w.stop = MagicMock()
        w._store_ledger = MagicMock()

    def test_current_result_accepted_and_stale_clear_rejected(self):
        w = self.window
        w.timeline = MagicMock()
        w.start_at = 0
        w.post_session(2, 'clear', 3)
        w.post_session(2, 'translated', 4, 'CURRENT', 'en', 0, 0)
        w.pump()
        w.overlay_state.clear.assert_not_called()
        w.last_translation_var.set.assert_called_once_with('CURRENT')
        w.overlay_state.set.assert_not_called()  # The durable display manager owns blocks.

    def test_no_worker_starts_during_close(self):
        w = self.window
        w.closing = True
        with patch.object(self.module.threading, 'Thread') as thread:
            w._spawn(lambda: None)
        thread.assert_not_called()

    def test_old_session_and_stopped_results_rejected_at_ui_consumption(self):
        w = self.window
        w.post_session(1, 'translated', 4, 'OLD', 'en', 0, 0)
        w.post_session(2, 'translated', 3, 'STALE', 'en', 0, 0)
        w.running = False
        w.post_session(2, 'translated', 4, 'STOPPED', 'en', 0, 0)
        w.pump()
        w.overlay_state.set.assert_not_called()
        w.root.after.assert_called_once()

    def test_engine_init_failure_keeps_pump_alive(self):
        w = self.window
        with patch.object(self.module, 'TranslationEngine', side_effect=RuntimeError('dummy')):
            w.translate_worker({'api_key_runtime': 'dummy', 'model': 'gpt-6.1-sol'},
                               threading.Event(), 2, queue.Queue(), ContextMemory('', ''))
        w.pump()
        w.stop.assert_called_once()
        w.root.after.assert_called_once()

    def test_close_waits_for_workers_before_destroy(self):
        w = self.window
        worker = MagicMock()
        worker.is_alive.return_value = True
        w.workers = [worker]
        w.pump_after = 'pump-timer'
        w.closing = False
        w.close()
        w.root.destroy.assert_not_called()
        worker.is_alive.return_value = False
        w.server = None
        w._finish_close()
        w._store_ledger.assert_called()
        w.root.destroy.assert_called_once()
        w.root.after_cancel.assert_any_call('pump-timer')


if __name__ == '__main__':
    unittest.main()
