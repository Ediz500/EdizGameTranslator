"""Real Windows Tk startup/close smoke test, isolated from credentials and API."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
from types import SimpleNamespace
from contextlib import closing
import sqlite3


@unittest.skipUnless(sys.platform == 'win32', 'Windows only')
class GuiTests(unittest.TestCase):
    def test_diagnostic_start_real_ui_fake_obs_ocr_zero_api(self):
        import tkinter as tk
        from PIL import Image
        import app
        fake_obs = MagicMock()
        import time
        def read():
            time.sleep(.02)
            return Image.new('RGB',(1920,1080))
        fake_obs.read.side_effect=read
        ocr = MagicMock(return_value=SimpleNamespace(txts=['Follow me!'], scores=[.99], boxes=None))
        with tempfile.TemporaryDirectory() as folder, patch('app.secret_get', return_value=''), patch('app.secret_save'), patch('app.config_folder', return_value=Path(folder)), patch('core.config_folder', return_value=Path(folder)), patch('rapidocr.RapidOCR', return_value=ocr), patch('app.WarmNMTClient') as engine, patch('app.VirtualCamera',return_value=fake_obs), patch.object(app.MainWindow,'_obs'), patch('app.messagebox.askyesno', return_value=True):
            root = tk.Tk()
            window = app.MainWindow(root)
            self.assertFalse(window.diagnostic_mode.get())
            self.assertFalse(window.diagnostic_logs.get())
            window.diagnostic_mode.set(True)
            window.diagnostic_logs.set(True)
            window.source.set('Fake OBS source')
            window.camera_config.set('mock-collection.json')
            window.interval.set('0.28')
            window.start()
            timeout = None
            def finish_when_ready():
                if ocr.call_count >= 3:
                    root.after_cancel(timeout)
                    window.close()
                else:
                    root.after(30,finish_when_ready)
            root.after(30,finish_when_ready)
            timeout = root.after(5000,window.close)
            root.mainloop()
            engine.assert_not_called()
            self.assertGreaterEqual(ocr.call_count,3)
            fake_obs.close.assert_called_once()
            with closing(sqlite3.connect(Path(folder)/'subtitles.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT text,status FROM subtitles').fetchall(),
                                 [('Follow me!','diagnostic_only')])
            self.assertEqual(len(list((Path(folder)/'diagnostics').glob('*.jsonl'))),1)

    def test_single_instance_lock(self):
        from instance_lock import InstanceLock
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'instance.lock'
            first = InstanceLock(path)
            try:
                with self.assertRaises(OSError):
                    InstanceLock(path)
            finally:
                first.close()
            second = InstanceLock(path)
            second.close()

    def test_real_window_opens_and_closes_without_api(self):
        import tkinter as tk
        import app
        with tempfile.TemporaryDirectory() as folder, patch('app.secret_get', return_value=''), patch('app.config_folder', return_value=Path(folder)), patch('core.config_folder', return_value=Path(folder)):
            root = tk.Tk()
            window = app.MainWindow(root)
            try:
                root.update()
                self.assertTrue(root.winfo_viewable())
                self.assertEqual(root.title(), app.APP_TITLE)
                self.assertIsNotNone(window.server)
            finally:
                window.close()
            self.assertFalse((Path(folder) / 'ledger.json').exists())
