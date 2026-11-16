"""Local session ownership and shutdown regressions."""
from bootstrap import configure_paths
configure_paths()
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


class SessionTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('p1_app', Path(__file__).resolve().parents[1] / 'src/ediz_game_translator/app.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'ediz_game_translator.capture.obs_capture': MagicMock()}):
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
        w.engine_info_var=MagicMock();w.session_info_var=MagicMock()
        w.local_engine=MagicMock();w.local_device=MagicMock()
        w.workers=[];w.preview_active=False;w.capture_feed=None;w.diagnostic_active=False
        w.metric_vars={k:MagicMock() for k in ('ocr','translation','capacity','renderer','active','removal')}
        w.timeline=MagicMock();w.start_at=0;w.refresh_live_preview=MagicMock()
        w.overlay = MagicMock()
        w.overlay.enabled=False
        w.overlay_state = MagicMock()
        w.overlay_state.snapshot.return_value=dict(style={},blocks=[],waiting=0,backlog_seconds=0,translation_pending=0,overloaded=False)
        w.last_translation_var=MagicMock();w.connection_var=MagicMock()
        w.stop = MagicMock()

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
        with patch.object(self.module, 'LocalTranslationCoordinator', side_effect=RuntimeError('dummy')):
            w.translate_worker({'_store':MagicMock(),'_capture_session':'s'},threading.Event(),2)
        w.pump()
        w.stop.assert_called_once()
        w.root.after.assert_called_once()

    def test_actionable_error_remains_visible_after_safety_stop(self):
        w=self.window
        w.post_session(2,'error','Yerel model klasörü bulunamadı; Bağlantılar sayfasından seçin.')
        w.post_session(2,'stopped')
        w.pump()
        w.status_var.set.assert_called_with('Güvenlik için durduruldu. Yerel model klasörü bulunamadı; Bağlantılar sayfasından seçin.')

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
        w.root.destroy.assert_called_once()
        w.root.after_cancel.assert_any_call('pump-timer')


if __name__ == '__main__':
    unittest.main()
