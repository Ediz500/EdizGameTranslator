"""Preserved migration, HTTP acknowledgements and lifecycle regressions."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch

from subtitle_store import SubtitleStore
from overlay_server import SharedOverlayState,launch_server


class StoreAndProtocolTests(unittest.TestCase):
    def test_migration_leaves_legacy_rows_and_restart_cancels_old_scene_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'private.sqlite3';store=SubtitleStore(p)
            row=store.accept('old','Original',1,1,1,1,.99,'legacy')
            store.status(row,'translated_hidden','Old translation')
            store.db.commit();store.close()
            store=SubtitleStore(p)
            self.assertEqual(store.db.execute('SELECT text,status,translated FROM subtitles').fetchone(),('Original','translated_hidden','Old translation'))
            job=store.enqueue_translation('new',row,'Source','local:fixture',2);store.complete_translation(job,'New',3)
            store.db.close()  # Simulated crash without a clean close.
            reopened=SubtitleStore(p)
            self.assertEqual(reopened.db.execute('SELECT display_state,cancel_reason FROM translation_jobs').fetchone(),('cancelled','process_restart'))
            reopened.close()

    def test_http_ack_generation_guard_and_no_pre_ack_countdown(self):
        from urllib.request import urlopen,Request
        from urllib.error import HTTPError
        state=SharedOverlayState();state.set('Gidelim.',10);server=launch_server(state,0)
        url=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(url+'/state') as r:first=json.load(r)
            self.assertIsNone(first['blocks'][0]['started'])
            payload=dict(generation=first['generation'],ids=[first['blocks'][0]['id']])
            with urlopen(Request(url+'/ack',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})) as r:self.assertEqual(r.status,204)
            self.assertIsNotNone(state.snapshot()['blocks'][0]['started'])
            state.clear();self.assertEqual(state.ack(payload['ids'],payload['generation']),0)
            with self.assertRaises(HTTPError):urlopen(Request(url+'/ack',data=b'{}',headers={'Content-Type':'text/plain'}))
            with self.assertRaises(HTTPError):urlopen(Request(url+'/ack',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://example.invalid'}))
        finally:server.shutdown();server.server_close();state.close()

    def test_stop_while_browser_has_old_snapshot_cannot_restore_blocks(self):
        state=SharedOverlayState();state.set('Eski',10);old=state.snapshot()
        state.clear('source_lost');state.set('Yeni',10)
        self.assertEqual(state.ack([b['id'] for b in old['blocks']],old['generation']),0)
        self.assertEqual(state.current(),'Yeni');state.close()

    def test_actual_recorded_spiderman_replay_does_not_hide_existing_translations(self):
        from replay_display import compare
        data=json.loads(Path(__file__).with_name('spiderman_display_timing.json').read_text())
        result=compare(data)
        self.assertEqual((result['accepted'],result['existing_translations'],result['old_delivery_marked'],result['new_simulated_visible']),(57,49,19,49))
