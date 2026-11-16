"""Real read-only OBS/Virtual Camera pipeline benchmark; never starts OpenAI."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from ediz_game_translator.app import secret_get
from ediz_game_translator.core import load_settings
from ediz_game_translator.capture.capture_pipeline import CaptureRunner,DiagnosticLog
from ediz_game_translator.capture.frame_sources import LatestFrames
from legacy_capture import ScreenshotFrames,LegacyObsSource as ObsSource
from ediz_game_translator.capture.obs_capture import crop_frame
from ediz_game_translator.capture.ocr_profiles import create_ocr
from ediz_game_translator.storage.subtitle_store import SubtitleStore
from ediz_game_translator.capture.virtual_camera import VirtualCamera,LiveObsGuard


def get_stats(obs):
    r=obs.client.get_stats()
    return {key:getattr(r,key,None) for key in ('active_fps','render_skipped_frames','render_total_frames',
            'output_skipped_frames','output_total_frames','average_frame_render_time','cpu_usage')}


def video_settings(obs):
    response=obs.client.get_video_settings()
    return {key:getattr(response,key) for key in response.attrs()}


def run(args):
    s=load_settings()
    metadata=ObsSource(secret_get('obs_password'),s['obs_port'])
    before=get_stats(metadata)
    scene_before=metadata.client.get_current_program_scene().current_program_scene_name
    video_before=video_settings(metadata)
    def factory():
        obs=ObsSource(secret_get('obs_password'),s['obs_port'],width=args.width)
        if args.method=='virtual_camera':
            try:
                return VirtualCamera(args.config,s['obs_source'],args.width,True,LiveObsGuard(obs))
            except Exception:
                obs.close()
                raise
        return ScreenshotFrames(obs,s['obs_source'])
    stop=threading.Event()
    timer=threading.Timer(args.seconds,stop.set)
    buffered=None
    ocr=create_ocr(args.profile)
    with tempfile.TemporaryDirectory() as folder:
        store=SubtitleStore(Path(folder)/'benchmark.sqlite3')
        try:
            buffered=LatestFrames(factory,stop,period=0 if args.method=='virtual_camera' else .15)
            runner=CaptureRunner(buffered.read,
                lambda img:crop_frame(img,*[s[k] for k in ('crop_left','crop_top','crop_right','crop_bottom')]),
                ocr,store,'live-benchmark',DiagnosticLog(),lambda:None,lambda *a:None,.28)
            timer.start()
            try:
                runner.run(stop)
            except InterruptedError:
                pass
            report=runner.metrics.summary()
            report.update(kind='real_capture_no_api_no_output',method=args.method,profile=args.profile,
                width=args.width,requested_seconds=args.seconds,accuracy=None,
                processed_fps=report['frames']/report['wall_seconds'])
            latest=buffered.latest
            if latest:
                report.update(actual_image_size=list(latest.image.size),source_reads=latest.sequence)
        finally:
            timer.cancel(); stop.set()
            if buffered:buffered.close()
            store.close()
    report.update(obs_before=before,obs_after=get_stats(metadata))
    report['program_scene_unchanged']=(metadata.client.get_current_program_scene().current_program_scene_name==scene_before)
    report['video_settings_unchanged']=(video_settings(metadata)==video_before)
    metadata.close()
    Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser()
    p.add_argument('--method',choices=('websocket','virtual_camera'),default='websocket')
    p.add_argument('--width',type=int,choices=(960,1280,1920),default=960)
    p.add_argument('--seconds',type=int,default=20)
    p.add_argument('--profile',default='bounded960')
    p.add_argument('--config')
    p.add_argument('--output',default='PERF_LIVE_PIPELINE.json')
    a=p.parse_args()
    if a.method=='virtual_camera' and not a.config:p.error('--config required')
    if not 1<=a.seconds<=600:p.error('seconds must be 1..600')
    run(a)
