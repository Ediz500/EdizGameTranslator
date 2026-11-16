"""Read existing localhost OBS state only. Never changes routes or opens a camera."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from ediz_game_translator.core import load_settings
from ediz_game_translator.app import secret_get
from ediz_game_translator.capture.obs_capture import ObsSource
from ediz_game_translator.capture.virtual_camera import VirtualCamera,LiveObsGuard,resolve_collection_path


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    report=dict(kind='real_obs_read_only_guard',samples=[],error=None);obs=None
    try:
        s=load_settings();obs=ObsSource(secret_get('obs_password'),s['obs_port'],s['capture_width'])
        camera=VirtualCamera.__new__(VirtualCamera)
        camera.path=resolve_collection_path(obs,s.get('camera_config',''));camera.source=s['obs_source']
        camera.validator=LiveObsGuard(obs);camera._config_signature=None;camera._config_data=None
        for _ in range(100):report['samples'].append(camera._check())
    except Exception as exc:report['error']=type(exc).__name__  # no credentials, paths or source names
    finally:
        if obs:obs.close()
    Path(a.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
