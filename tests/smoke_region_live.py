"""Manual real-source editor check. No game images/text or user settings are saved."""
from copy import deepcopy
import json
import argparse
from pathlib import Path
import socket
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from core import load_settings


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--running',action='store_true');args=parser.parse_args()
    settings=load_settings()
    with socket.socket() as probe:
        probe.settimeout(.2)
        if probe.connect_ex(('127.0.0.1',8788))==0:
            print('SKIP: another overlay instance is running');return
    password=app.secret_get('obs_password')
    count=[0];model_count=[0]
    original=app.MainWindow._make_capture_source
    original_ocr=app.create_ocr
    def source(window,s):
        count[0]+=1
        return original(window,s)
    def ocr(profile):
        model_count[0]+=1
        return original_ocr(profile)
    with tempfile.TemporaryDirectory() as folder,patch('app.load_settings',return_value=deepcopy(settings)),patch('app.config_folder',return_value=Path(folder)),patch('core.config_folder',return_value=Path(folder)),patch('app.secret_get',side_effect=lambda key:password if key=='obs_password' else ''),patch('app.secret_save'),patch('app.TranslationEngine') as api,patch.object(app.MainWindow,'_make_capture_source',new=source),patch('app.create_ocr',side_effect=ocr):
        root=tk.Tk();window=app.MainWindow(root)
        if args.running:
            window.diagnostic_mode.set(True);window.diagnostic_logs.set(False);window.start()
        window.open_region_editor();editor=window.region_editor
        if editor is None:window.close();print('SKIP: preview unavailable');return
        report=dict(kind='real_editor_preview_no_api',method=settings['capture_method'],running_ocr=args.running)
        sequences=set();deadline=time.monotonic()+20;paused_at=[None]
        def finish():
            report.update(source_adapter_opens=count[0],ocr_engine_initializations=model_count[0],api_clients=api.call_count,
                          preview_packets=len(sequences),ocr_test_completed=editor.result is not None,
                          ocr_text_lines=len(editor.result['texts']) if editor.result else 0)
            if args.running:
                editor.cancel()
                report['capture_survived_editor_close']=window.running and window.capture_feed is not None
            window.close()
        def poll():
            if time.monotonic()>deadline:
                report['timeout']=True;finish();return
            if editor.packet is not None:sequences.add(editor.packet.sequence)
            if len(sequences)>=3 and paused_at[0] is None:
                editor.toggle_pause();paused_at[0]=time.monotonic()
                report['image_size']=list(editor.packet.image.size)
                report['paused_packet']=editor.packet.sequence
            if paused_at[0] is not None and time.monotonic()-paused_at[0]>2:
                if not editor.in_test and editor.result is None:editor.test_ocr()
                if editor.result is not None:
                    report['pause_kept_frame']=editor.packet.sequence==report['paused_packet']
                    feed=window.capture_feed
                    report['source_kept_running']=bool(feed and feed.peek().sequence>editor.packet.sequence)
                    report['mailbox_consumed']=feed.consumed if feed else None
                    if not args.running:report['peek_did_not_consume']=bool(feed and feed.consumed==0)
                    finish();return
            root.after(100,poll)
        root.after(100,poll);root.mainloop()
        report['workers_closed']=all(not worker.is_alive() for worker in window.workers)
        report['editor_closed']=editor.closed
        api.assert_not_called()
    output='REGION_LIVE_SHARED_CHECK.json' if args.running else 'REGION_LIVE_CHECK.json'
    Path(output).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
