"""Run the actual overlay JS with a deterministic DOM/network/clock harness."""
from bootstrap import configure_paths
configure_paths()
from pathlib import Path
import shutil
import subprocess
import unittest
from ediz_game_translator.subtitles.overlay_view import OVERLAY_HTML


@unittest.skipUnless(shutil.which('node'),'Node.js required for browser-script regressions')
class OverlayConnectionTests(unittest.TestCase):
    def run_case(self,name):
        result=subprocess.run([shutil.which('node'),str(Path(__file__).with_name('overlay_connection_cases.js')),name],
            input=OVERLAY_HTML,text=True,encoding='utf8',capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_polling_error_clears_and_recovers(self):self.run_case('polling_error_clears_and_recovers')
    def test_hung_poll_has_deadline_and_retries(self):self.run_case('hung_poll_has_deadline_and_retries')
    def test_silent_sse_expires_and_falls_back(self):self.run_case('silent_sse_expires_and_falls_back')
    def test_sse_without_first_snapshot_switches_to_polling(self):self.run_case('sse_without_first_snapshot_switches_to_polling')
    def test_sse_error_rejects_late_old_events(self):self.run_case('sse_error_rejects_late_old_events')
    def test_healthy_heartbeats_do_not_blank_stable_caption(self):self.run_case('healthy_heartbeats_do_not_blank_stable_caption')
    def test_healthy_heartbeats_preserve_ack_with_slow_renderer(self):self.run_case('healthy_heartbeats_preserve_ack_with_slow_renderer')
    def test_malformed_state_fails_closed(self):self.run_case('malformed_state_fails_closed')
    def test_http_503_does_not_preserve_previous_dom(self):self.run_case('http_503_does_not_preserve_previous_dom')
    def test_delayed_old_http_response_cannot_resurrect_after_expiry(self):self.run_case('delayed_old_http_response_cannot_resurrect_after_expiry')
    def test_old_animation_ack_is_fenced_on_same_session_recovery(self):self.run_case('old_animation_ack_is_fenced_on_same_session_recovery')
    def test_reconnect_empty_state_keeps_text_and_mask_removed(self):self.run_case('reconnect_empty_state_keeps_text_and_mask_removed')
