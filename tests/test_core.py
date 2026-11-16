from bootstrap import configure_paths
configure_paths()
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ediz_game_translator.core import SubtitleTimeline, clean_ocr, choose_subtitle, key_for
from ediz_game_translator.subtitles.overlay_server import SharedOverlayState, launch_server


class CoreTests(unittest.TestCase):
    def test_ocr_normalization(self):
        self.assertEqual(clean_ocr('  Hello   world\n  today '), 'Hello world today')
        self.assertEqual(key_for('Hello, world!'), key_for('hello world'))

    def test_subtitle_chooses_center_not_sidebars(self):
        r = SimpleNamespace(
            txts=['Ammo: 70', 'Wait for me!', 'Please!', 'Press X'],
            scores=[.9, .96, .98, .90],
            boxes=[[[0, 1], [90, 1], [90, 20], [0, 20]],
                   [[300, 30], [670, 30], [670, 50], [300, 50]],
                   [[330, 60], [650, 60], [650, 80], [330, 80]],
                   [[330, 90], [650, 90], [650, 109], [330, 109]]]
        )
        self.assertEqual(choose_subtitle(r, 1000), 'Wait for me! Please!')


    def test_srt(self):
        s = SubtitleTimeline()
        s.add(1, 'Merhaba')
        s.add(4, 'Gidelim')
        subtitle = s.srt()
        self.assertIn('00:00:01,000 --> 00:00:04,000', subtitle)
        self.assertIn('Gidelim', subtitle)

    def test_overlay_state_json(self):
        import json
        s = SharedOverlayState()
        s.set('Merhaba', 2)
        p = json.loads(s.json())
        self.assertEqual(p['text'], 'Merhaba')
        self.assertEqual(s.current(), 'Merhaba')
        s.clear()
        self.assertEqual(s.current(), '')

    def test_overlay_http(self):
        from urllib.request import urlopen
        state = SharedOverlayState()
        server = launch_server(state, 0)
        try:
            port = server.server_address[1]
            state.set('Altyazı denemesi')
            with urlopen(f'http://127.0.0.1:{port}/state', timeout=2) as response:
                self.assertIn('Altyazı denemesi', response.read().decode())
            with urlopen(f'http://127.0.0.1:{port}/overlay', timeout=2) as response:
                self.assertIn('text/html', response.headers['Content-Type'])
                self.assertIn('fetch', response.read().decode())
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
