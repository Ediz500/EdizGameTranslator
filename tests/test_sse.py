from bootstrap import configure_paths
configure_paths()
import json
import time
import unittest
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from ediz_game_translator.subtitles.overlay_server import SharedOverlayState,launch_server


class SSETests(unittest.TestCase):
    def test_events_deliver_completed_job_and_preserve_generation_ack(self):
        state=SharedOverlayState();state.transport='sse';server=launch_server(state,0)
        url=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(url+'/overlay') as r:self.assertIn('const USE_SSE=true;',r.read().decode())
            with urlopen(url+'/events',timeout=2) as stream:
                self.assertEqual(stream.headers['Content-Type'],'text/event-stream')
                self.assertTrue(stream.readline().startswith(b'data: '));stream.readline()
                state.set('Gerçek transport testi.',10)
                line=stream.readline()
                data=json.loads(line[6:])
                self.assertEqual(data['blocks'][0]['text'],'Gerçek transport testi.')
                self.assertIsNone(data['blocks'][0]['started'])
                payload=dict(ids=[data['blocks'][0]['id']],generation=data['generation'])
                with urlopen(Request(url+'/ack',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})) as r:
                    self.assertEqual(r.status,204)
                self.assertIsNotNone(state.snapshot()['blocks'][0]['started'])
                self.assertEqual(state.manager.store.db.execute("SELECT transport FROM transport_events").fetchone()[0],'sse')
                state.clear()
                self.assertEqual(state.ack(payload['ids'],payload['generation']),0)
        finally:server.shutdown();server.server_close();state.close()

    def test_untrusted_origin_is_rejected(self):
        state=SharedOverlayState();server=launch_server(state,0)
        try:
            with self.assertRaises(HTTPError) as ctx:
                urlopen(Request(f'http://127.0.0.1:{server.server_port}/events',headers={'Origin':'https://example.invalid'}))
            self.assertEqual(ctx.exception.code,403)
        finally:server.shutdown();server.server_close();state.close()

    def test_polling_remains_default_until_measured(self):
        state=SharedOverlayState();server=launch_server(state,0)
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}/overlay') as r:
                self.assertIn('const USE_SSE=false;',r.read().decode())
        finally:server.shutdown();server.server_close();state.close()

    def test_unchanged_snapshot_is_a_js_visible_heartbeat(self):
        state=SharedOverlayState();state.set('Sabit sentetik replik.',10);server=launch_server(state,0)
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}/events',timeout=1.4) as stream:
                first=json.loads(stream.readline()[6:]);stream.readline();began=time.monotonic()
                second=stream.readline();self.assertTrue(second.startswith(b'data: '))
                data=json.loads(second[6:]);self.assertEqual(data['generation'],first['generation'])
                self.assertEqual(data['blocks'],first['blocks']);self.assertLess(time.monotonic()-began,1.2)
        finally:server.shutdown();server.server_close();state.close()

    def test_new_stream_gets_only_current_state_after_source_replacement(self):
        from ediz_game_translator.storage.subtitle_store import SubtitleStore
        store=SubtitleStore(':memory:');state=SharedOverlayState();state.bind(store,'s',live=True)
        store.enable_live_session('s',stale=2);now=time.monotonic()
        def entry(text,key):
            row=store.accept('s',text,now,now,0,now,.99,'fixture')
            return dict(subtitle_id=row,track_key=key,canonical=text,speaker='')
        a=entry('First source.','A');store.publish_sources('s',[a],now)
        old=store.enqueue_translation('s',a['subtitle_id'],a['canonical'],'local:fixture',now)
        store.claim_translation('s',now)
        b=entry('Current source.','B');store.publish_sources('s',[b],now,retired=['A'])
        job=store.enqueue_translation('s',b['subtitle_id'],b['canonical'],'local:fixture',now)
        store.complete_translation(job,'Güncel B.',now);store.complete_translation(old,'Eski A.',now)
        server=launch_server(state,0)
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}/events',timeout=2) as stream:
                data=json.loads(stream.readline()[6:])
                self.assertEqual([b['text'] for b in data['blocks']],['Güncel B.'])
                self.assertEqual(store.db.execute('SELECT translated FROM translation_jobs WHERE id=?',(old,)).fetchone()[0],'Eski A.')
        finally:server.shutdown();server.server_close();state.close();store.close()
