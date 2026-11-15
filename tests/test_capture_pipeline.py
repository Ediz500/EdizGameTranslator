import json
from contextlib import closing
from pathlib import Path
import queue
import sqlite3
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from capture_pipeline import CaptureRunner, DiagnosticLog, SubtitleGate, same_line
from subtitle_store import SubtitleStore
from benchmark_capture import LegacyGate, replay
from core import subtitle_observation


def result(text='Follow me!', score=.98):
    texts = text.split('\n') if text else []
    return SimpleNamespace(txts=texts, scores=[score]*len(texts), boxes=None)


class GateTests(unittest.TestCase):
    def test_reliable_short_single_frame(self):
        d = SubtitleGate().observe('Get down!', .98, 0)
        self.assertTrue(d.accepted)
        self.assertEqual(d.reason, 'high_confidence')

    def test_uncertain_needs_confirmation_and_tolerates_known_noise(self):
        gate = SubtitleGate()
        self.assertFalse(gate.observe('F0llow the guards.', .8, 0).accepted)
        decision = gate.observe('Follow the guards.', .9, .28)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.text, 'Follow the guards.')
        self.assertEqual(decision.first_seen, 0)
        self.assertFalse(gate.observe('F0llow the guards.', .8, .56).accepted)

    def test_meaningful_changes_and_partial_are_distinct(self):
        for a,b in [('Go east.', 'Go west.'), ('I can go.', "I can't go."),
                    ('We should', 'We should leave'), ('Take 10.', 'Take 11.'),
                    ('Were here?', "We're here."), ('Guard 01', 'Guard 11')]:
            self.assertFalse(same_line(a,b), (a,b))

    def test_low_confidence_is_not_confirmed_and_blank_separates_repeat(self):
        gate = SubtitleGate()
        for i in range(3):
            self.assertFalse(gate.observe('zxq! grr 88!', .49, i*.28).accepted)
        self.assertTrue(gate.observe('Run!', .98, 1).accepted)
        self.assertTrue(gate.observe('', 0, 1.28).changed)
        self.assertTrue(gate.observe('Run!', .98, 1.56).accepted)

    def test_two_line_confidence_is_minimum_of_selected_lines(self):
        text, score = subtitle_observation(SimpleNamespace(txts=['Stay close.', 'We are almost there.'],
            scores=[.98,.7], boxes=None), 1920)
        self.assertEqual(text, 'Stay close. We are almost there.')
        self.assertEqual(score, .7)

    def test_nonfinite_ocr_confidence_is_filtered(self):
        for score in (float('nan'),float('inf'),1.5):
            self.assertEqual(subtitle_observation(result(score=score),1920),('',0))

    def test_fixture_comparison(self):
        class Adapter:
            def __init__(self): self.gate = SubtitleGate()
            def observe(self, text, confidence, now):
                d = self.gate.observe(text, confidence, now)
                return d.text if d.accepted else None
        before = replay(LegacyGate, .8)
        after = replay(Adapter, .28)
        self.assertEqual(before['captured'], 4)
        self.assertEqual(after['captured'], 12)
        self.assertEqual(after['false_accepts'], 0)
        self.assertTrue(all(r['duplicates']==0 for r in after['cases']))


class PipelineTests(unittest.TestCase):
    def test_no_log_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            log = DiagnosticLog()
            log.write('frame', raw_texts=['private'])
            log.close()
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_storage_before_dispatch_and_duration_and_timings(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder)/'subtitles.sqlite3'
            store = SubtitleStore(db_path)
            path = Path(folder)/'trace.jsonl'
            log = DiagnosticLog(path)
            rows = []
            def accept(row,text,at):
                with closing(sqlite3.connect(db_path)) as connection:
                    self.assertEqual(connection.execute('SELECT text FROM subtitles WHERE id=?',(row,)).fetchone()[0],text)
                rows.append(row)
            ocr = MagicMock(side_effect=[result(), result(), result('')])
            runner = CaptureRunner(lambda: object(), lambda image: SimpleNamespace(width=1920),
                ocr, store, 'unique-session', log, MagicMock(), accept)
            for _ in range(3): runner.step()
            store.status(rows[0],'translated','Yerel test',queue_wait_ms=12,translation_ms=34)
            store.close()
            log.close()
            with closing(sqlite3.connect(db_path)) as db:
                row = db.execute('SELECT first_seen_mono,last_seen_mono,end_mono FROM subtitles').fetchone()
                self.assertLessEqual(row[0],row[1])
                self.assertGreaterEqual(row[2],row[1])
                self.assertEqual(db.execute('SELECT queue_wait_ms,translation_ms FROM subtitles').fetchone(),(12,34))
            self.assertEqual(len(rows),1)
            records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            frames = [r for r in records if r['kind']=='frame']
            self.assertEqual(len([r for r in records if r['kind']=='subtitle_end']),1)
            self.assertEqual([x['reason'] for x in frames],['high_confidence','duplicate','empty'])
            for f in frames:
                self.assertLessEqual(f['request_mono'], f['received_mono'])
                self.assertLessEqual(f['ocr_start'], f['ocr_end'])
                self.assertGreaterEqual(f['ocr_ms'],0)
                self.assertIn('raw_texts',f)

    def test_sequential_under_slow_ocr_and_stop_discards_late_frame(self):
        stop = threading.Event()
        calls = []
        def ocr(image):
            calls.append('ocr')
            stop.set()
            return result()
        store, accept = MagicMock(), MagicMock()
        runner = CaptureRunner(lambda: calls.append('frame'), lambda _: SimpleNamespace(width=1920),
            ocr, store, 's', DiagnosticLog(), MagicMock(), accept)
        runner.run(stop)
        self.assertEqual(calls,['frame','ocr'])
        accept.assert_not_called()
        store.accept.assert_not_called()

    def test_disk_error_does_not_dispatch_unrecorded_subtitle(self):
        store, accept = MagicMock(), MagicMock()
        store.accept.side_effect = sqlite3.OperationalError('full')
        runner = CaptureRunner(lambda: None, lambda _: SimpleNamespace(width=1920),
            lambda _: result(), store, 's', DiagnosticLog(), MagicMock(), accept)
        with self.assertRaises(sqlite3.OperationalError): runner.step()
        accept.assert_not_called()

    def test_invalid_intervals(self):
        for interval in (.005, float('nan'), float('inf'), 6):
            with self.assertRaises(ValueError):
                CaptureRunner(None,None,None,None,None,None,None,None,interval)

    def test_capture_keeps_all_rows_while_consumer_is_blocked(self):
        # A blocked translator must retain every job, not only source records.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'lines.sqlite3'
            store = SubtitleStore(path)
            sequence = [0]
            def change(): sequence[0] += 1
            def accept(row,text,at):
                store.enqueue_translation('s',row,text,'gpt-6-luna',at)
            ocr = MagicMock(side_effect=[result('Watch out!'),result('Run now!'),result('Follow me!')])
            runner = CaptureRunner(lambda: None, lambda _: SimpleNamespace(width=1920),
                ocr, store,'s',DiagnosticLog(),change,accept)
            runner.step()
            held = store.claim_translation('s',time.monotonic())
            runner.step()
            runner.step()
            with closing(sqlite3.connect(path)) as db:
                records = db.execute('SELECT text,status FROM subtitles ORDER BY id').fetchall()
                self.assertEqual(len(records),3)
                self.assertEqual(records[1][1],'queued')
            self.assertEqual(store.claim_translation('s',time.monotonic())['source'],'Run now!')
            self.assertEqual(store.claim_translation('s',time.monotonic())['source'],'Follow me!')
            self.assertEqual(held['source'],'Watch out!')
            store.close()

    def test_diagnostic_worker_cannot_initialize_api(self):
        import app
        w = app.MainWindow.__new__(app.MainWindow)
        with patch('app.TranslationEngine') as api:
            w.translate_worker({'_diagnostic': True},None,None,None,None)
        api.assert_not_called()

    def test_capture_lock_and_obs_released_even_if_log_close_fails(self):
        import app
        w = app.MainWindow.__new__(app.MainWindow)
        w.capture_lock = threading.Lock()
        w.post = MagicMock()
        w.post_session = MagicMock()
        w._obs = MagicMock()
        source=MagicMock()
        source.read.return_value=SimpleNamespace(width=960)
        log = MagicMock()
        log.close.side_effect = OSError('full')
        with patch('app.DiagnosticLog', return_value=log), patch('rapidocr.RapidOCR'), patch('app.CaptureRunner'),patch.object(w,'_make_capture_source',return_value=source):
            with self.assertRaises(OSError):
                w.capture_worker({'_log_path':None,'_store':MagicMock(),'_capture_session':'s',
                    '_ready':threading.Event(),
                    '_diagnostic':True,'scan_interval':.28,'obs_source':'s',
                    'crop_left':0,'crop_top':65,'crop_right':100,'crop_bottom':94},
                    threading.Event(),1,queue.Queue())
        self.assertFalse(w.capture_lock.locked())
        source.close.assert_called_once()

    def test_test_ai_button_blocked_in_diagnostics(self):
        import app
        w = app.MainWindow.__new__(app.MainWindow)
        w.diagnostic_active = True
        w.status_var = MagicMock()
        with patch('app.TranslationEngine') as api, patch.object(w,'prepare') as prepare:
            w.test_ai()
        api.assert_not_called()
        prepare.assert_not_called()

    def test_ocr_test_during_capture_opens_shared_editor_without_new_capture(self):
        import app
        w = app.MainWindow.__new__(app.MainWindow)
        w.capture_lock = threading.Lock()
        w.capture_lock.acquire()
        w.status_var = MagicMock()
        with patch.object(w,'prepare') as prepare,patch.object(w,'open_region_editor') as editor:
            w.test_ocr()
        editor.assert_called_once()
        prepare.assert_not_called()
        w.capture_lock.release()
