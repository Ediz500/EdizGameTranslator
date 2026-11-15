"""Opt-in real Virtual Camera + local OCR + FAKE translator + real HTTP check.

No OpenAI client, no user-setting writes, no persistent game text or frames.
--inject-test-line explicitly substitutes OCR output, to test transport with
an idle game. It does NOT validate real subtitle detection or translation.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from core import load_settings
from cloud_guard import NoCloudImports


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--inject-test-line',action='store_true');args=parser.parse_args()
    settings=load_settings();password=app.secret_get('obs_password')
    report=dict(kind='real_virtual_camera_fake_translation',injected_ocr=args.inject_test_line)
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',8788))==0:
            print('SKIP: application already running');return
    calls=[0];sources=[0];ocr_calls=[0];observations=[];original=app.MainWindow._make_capture_source
    class FakeEngine:
        def __init__(self,*args,**kwargs):self.closed=False
        def close(self):self.closed=True
        def translate(self,source):
            calls[0]+=1
            return dict(text='YEREL TEST: Ham oyun hattı doğrulandı.',complete=True,processing_ms=1)
    def source(window,s):
        sources[0]+=1;return original(window,s)
    original_ocr=app.create_ocr
    def create(profile):
        engine=original_ocr(profile)
        def ocr(image):
            start=time.perf_counter();r=engine(image);observations.append((time.perf_counter()-start)*1000);ocr_calls[0]+=1
            if args.inject_test_line:return SimpleNamespace(txts=['Scout: Stay close.'],scores=[.99],boxes=None)
            return r
        return ocr
    with tempfile.TemporaryDirectory() as folder,patch('app.load_settings',return_value=deepcopy(settings)),\
            patch('app.config_folder',return_value=Path(folder)),patch('core.config_folder',return_value=Path(folder)),\
            patch('app.secret_get',side_effect=lambda k:password if k=='obs_password' else ''),patch('app.secret_save'),\
            patch('app.WarmNMTClient',FakeEngine),patch('app.model_manifest',return_value=(Path(folder),{})),\
            patch.object(app.MainWindow,'_make_capture_source',source),patch('app.create_ocr',create),NoCloudImports() as cloud:
        root=tk.Tk();w=app.MainWindow(root)
        w.show_desktop.set(False)
        w.local_python.set(sys.executable);w.local_model_path.set(folder)
        before_obs=w._obs({'obs_password_runtime':password,**settings})
        try:
            scene_before=before_obs.client.get_current_program_scene().current_program_scene_name
            stats_before=before_obs.client.get_stats()
        finally:before_obs.close()
        w.start();deadline=time.monotonic()+25
        def finish():
            report.update(camera_opens=sources[0],local_ocr_calls=ocr_calls[0],fake_translations=calls[0],
                          overlay_verified=False,cloud_import_attempts=cloud.attempts)
            with urlopen('http://127.0.0.1:8788/state',timeout=2) as response:
                report['overlay_verified']=json.load(response)['text']=='YEREL TEST: Ham oyun hattı doğrulandı.'
            obs=w._obs({'obs_password_runtime':password,**settings})
            try:
                report['program_scene_unchanged']=obs.client.get_current_program_scene().current_program_scene_name==scene_before
                stats=obs.client.get_stats()
                report['obs_fps_before']=stats_before.active_fps;report['obs_fps_after']=stats.active_fps
            finally:obs.close()
            if observations:
                import statistics
                report['ocr_p50_ms']=statistics.median(observations)
            w.close()
        def poll():
            if w.overlay_state.current() or not w.running or time.monotonic()>deadline:
                finish();return
            root.after(100,poll)
        root.after(100,poll);root.mainloop()
        report['workers_closed']=all(not t.is_alive() for t in w.workers)
        assert not cloud.attempts
    output='DAILY_LIVE_INJECTED_CHECK.json' if args.inject_test_line else 'DAILY_LIVE_CHECK.json'
    Path(output).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
