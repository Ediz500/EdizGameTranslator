"""Real browser DOM-ACK harness; synthetic text, no model, camera, OBS or API."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from overlay_server import SharedOverlayState,launch_server
from local_benchmark import percentiles


def main():
    p=argparse.ArgumentParser();p.add_argument('--transport',choices=['poll','sse'],required=True)
    p.add_argument('--port',type=int,required=True);p.add_argument('--output',required=True);p.add_argument('--samples',type=int,default=20)
    a=p.parse_args();state=SharedOverlayState();state.transport=a.transport;server=launch_server(state,a.port)
    stop=threading.Event()
    report=dict(kind='real_browser_transport_only',transport=a.transport,samples=[],complete=False,
                no_ocr_or_model=True,physical_tv_verified=False)
    original=server.RequestHandlerClass
    class Handler(original):
        def do_GET(self):
            if self.path=='/stop':
                self.send_response(204);self.end_headers();stop.set()
            elif self.path=='/benchmark':
                data=json.dumps(report,ensure_ascii=False,indent=2).encode()
                self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            else:super().do_GET()
    server.RequestHandlerClass=Handler
    def pulses():
        deadline=time.monotonic()+90
        while not state.browser_seen and time.monotonic()<deadline:time.sleep(.02)
        time.sleep(.3)
        for i in range(a.samples):
            state.clear('benchmark_next_sample');state.set(f'ÖLÇÜM {i+1}: Örnek altyazı.',10)
            store=state.manager.store;deadline=time.monotonic()+2
            while time.monotonic()<deadline:
                with store.lock:
                    row=store.db.execute("""SELECT j.ready_mono,a.seen_mono FROM translation_jobs j
                        LEFT JOIN render_acks a ON a.job_id=j.id AND a.renderer='browser_dom_ack'""").fetchone()
                if row and row[1] is not None:
                    report['samples'].append(dict(ready_to_dom_ack_ms=(row[1]-row[0])*1000));break
                time.sleep(.002)
            else:report['samples'].append(dict(error='No real browser DOM acknowledgement'))
            time.sleep(.07+(i%5)*.013)  # Avoid locking phases to the 100ms poll.
        values=[r['ready_to_dom_ack_ms'] for r in report['samples'] if 'ready_to_dom_ack_ms' in r]
        report.update(complete=True,stages_ms=percentiles(values),missed_ack=a.samples-len(values))
        Path(a.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
    threading.Thread(target=pulses,daemon=True).start()
    print(f'Open http://127.0.0.1:{a.port}/overlay',flush=True)
    try:
        stop.wait(180)
    except KeyboardInterrupt:pass
    finally:server.shutdown();server.server_close();state.close()


if __name__=='__main__':main()
