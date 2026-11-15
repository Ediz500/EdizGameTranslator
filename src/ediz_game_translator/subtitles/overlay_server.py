"""Only localhost overlay output, never accepts API keys or network input."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from ediz_game_translator.subtitles.overlay_view import OVERLAY_HTML
from ediz_game_translator.subtitles.subtitle_display import DisplayManager
import uuid


class SharedOverlayState:
    def __init__(self):
        self.font=42;self.bottom=10;self.version=0
        self.lock=threading.RLock();self.manager=None;self.demo_store=None
        self.generation=uuid.uuid4().hex;self.browser_seen=0
        self.transport='poll'

    def bind(self,store,session,ready_first=False):
        with self.lock:
            self.clear('new_session')
            if self.demo_store is not None:
                self.demo_store.close();self.demo_store=None
            self.manager=DisplayManager(store,session,ready_first=ready_first)

    def set(self,text,lifetime=7):
        # Standalone manual/demo output only. Live jobs go directly to SQLite.
        from ediz_game_translator.storage.subtitle_store import SubtitleStore
        with self.lock:
            if self.manager is None:
                if self.demo_store is not None:self.demo_store.close()
                self.demo_store=SubtitleStore(':memory:')
                self.manager=DisplayManager(self.demo_store,'manual')
            store=self.manager.store;session=self.manager.session;now=time.monotonic()
            row=store.accept(session,'Manual example',now,now,time.time(),now,1,'manual')
            job=store.enqueue_translation(session,row,'Manual example','gpt-6-luna',now)
            store.complete_translation(job,text,now,duration=lifetime)
            self.version+=1

    def clear(self,reason='user_stop'):
        with self.lock:
            if self.manager is not None:self.manager.clear(reason)
            self.manager=None;self.generation=uuid.uuid4().hex;self.version+=1

    def snapshot(self):
        with self.lock:
            if self.manager:self.manager.browser_required=self.browser_seen>0 and time.monotonic()-self.browser_seen<2
            data=self.manager.snapshot() if self.manager else dict(blocks=[],waiting=0,backlog_seconds=0,translation_pending=0,overloaded=False)
            return dict(**data,generation=self.generation,font=self.font,bottom=self.bottom,version=self.version)

    def json(self):
        with self.lock:
            self.browser_seen=time.monotonic()
            data=self.snapshot()
            if self.manager:self.manager.sent()
            data['text']=data['blocks'][0]['text'] if data['blocks'] else ''
            data['until']=time.time()+data['blocks'][0]['remaining'] if data['blocks'] else 0
            return json.dumps(data,ensure_ascii=False).encode('utf-8')

    def record_sent(self,data,transport):
        with self.lock:
            if self.manager and data['generation']==self.generation:
                self.manager.store.transport_sent([b['id'] for b in data['blocks']],transport,time.monotonic())

    def wait_for_event(self,timeout=.02):
        with self.lock:store=self.manager.store if self.manager else None
        if store:
            with store.condition:store.condition.wait(timeout)
        else:time.sleep(timeout)

    def ack(self,ids,generation,renderer='browser_dom_ack'):
        with self.lock:
            if generation!=self.generation or self.manager is None:return 0
            return sum(self.manager.ack(job,renderer) for job in ids)

    def current(self):
        blocks=self.snapshot()['blocks']
        return blocks[0]['text'] if blocks else ''

    def close(self):
        self.clear('app_close')
        if self.demo_store is not None:self.demo_store.close();self.demo_store=None


def launch_server(state: SharedOverlayState, port: int = 8788):
    class OverlayHTTPServer(ThreadingHTTPServer):
        def shutdown(self):
            self.stream_stop.set()
            super().shutdown()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlparse(self.path).path
            if path=='/events':
                allowed={f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
                if self.headers.get('Origin') and self.headers['Origin'] not in allowed:
                    self.send_error(403);return
                if not self.server.stream_slots.acquire(blocking=False):
                    self.send_error(429);return
                try:
                    self.send_response(200);self.send_header('Content-Type','text/event-stream')
                    self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                    self.end_headers();last=None;heartbeat=time.monotonic()
                    self.connection.settimeout(2)
                    while not self.server.stream_stop.is_set():
                        body=state.json();data=json.loads(body)
                        signature=(data['generation'],data['font'],data['bottom'],data['waiting'],data['translation_pending'],
                            tuple((b['id'],b['text'],b['speaker'],b['started'],b['speed']) for b in data['blocks']))
                        if signature!=last:
                            self.wfile.write(b'data: '+body+b'\n\n');self.wfile.flush()
                            state.record_sent(data,'sse');last=signature;heartbeat=time.monotonic()
                        elif time.monotonic()-heartbeat>10:
                            self.wfile.write(b': keepalive\n\n');self.wfile.flush();heartbeat=time.monotonic()
                        state.wait_for_event()
                except (OSError,ConnectionError):pass
                finally:self.server.stream_slots.release()
                return
            if path in ("/", "/overlay"):
                state.browser_seen=time.monotonic()
                body = OVERLAY_HTML.replace('const USE_SSE=false;','const USE_SSE='+str(state.transport=='sse').lower()+';').encode("utf-8")
                typ = "text/html; charset=utf-8"
            elif path == "/state":
                body = state.json()
                typ = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", typ)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
                if path=='/state':
                    self.wfile.flush();state.record_sent(json.loads(body),'http')
            except (ConnectionAbortedError, BrokenPipeError):
                return

        def do_POST(self):
            # Same-origin JSON only; no permissive CORS or GET acknowledgement.
            origin=self.headers.get('Origin')
            allowed={f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
            if self.path!='/ack' or self.headers.get('Content-Type')!='application/json' or origin and origin not in allowed:
                self.send_error(403);return
            try:
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=1024:raise ValueError()
                payload=json.loads(self.rfile.read(length))
                ids=payload['ids'];generation=payload['generation']
                if not isinstance(ids,list) or len(ids)>3 or any(type(i) is not int for i in ids):raise ValueError()
                state.ack(ids,generation)
            except (ValueError,KeyError,TypeError):self.send_error(400);return
            self.send_response(204);self.end_headers()

    server = OverlayHTTPServer(("127.0.0.1", port), Handler)
    server.stream_stop=threading.Event();server.stream_slots=threading.BoundedSemaphore(4)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="OBS Overlay HTTP", daemon=True)
    thread.start()
    return server
