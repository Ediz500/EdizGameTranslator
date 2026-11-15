import json
import time
import unittest
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from overlay_server import SharedOverlayState,launch_server


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
