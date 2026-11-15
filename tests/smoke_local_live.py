"""Opt-in synthetic GUI + real OCR + real local model smoke. No paid API."""
import argparse
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw,ImageFont


def run(args):
    import app
    from core import DEFAULTS
    from overlay_server import launch_server
    image=Image.new('RGB',(960,540),'#20252d')
    ImageDraw.Draw(image).text((260,410),'MJ: We should leave now.',fill='white',
        font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',28))
    class Camera:
        def read(self):time.sleep(.016);return image
        def close(self):pass
    report=dict(kind='synthetic_gui_real_ocr_real_nmt',physical_tv_verified=False,ok=False)
    with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
        settings=deepcopy(DEFAULTS)
        settings.update(local_python=str(Path(args.python).resolve()),local_model_path=str(Path(args.model_path).resolve()),
            local_device=args.device,local_compute_type='int8_float16' if args.device=='cuda' else 'int8',
            local_workers=1 if args.device=='cuda' else 2,obs_source='Synthetic raw source',show_desktop=False)
        stack.enter_context(patch('app.load_settings',return_value=settings))
        for target in ('app.config_folder','core.config_folder'):stack.enter_context(patch(target,return_value=Path(folder)))
        stack.enter_context(patch('app.secret_get',return_value=''))
        stack.enter_context(patch('app.secret_save'))
        paid=stack.enter_context(patch('openai.OpenAI',side_effect=AssertionError('Paid API prohibited')))
        stack.enter_context(patch.object(app.MainWindow,'_make_capture_source',return_value=Camera()))
        stack.enter_context(patch('app.launch_server',side_effect=lambda state:launch_server(state,0)))
        errors=[]
        for name in ('showerror','showwarning','askyesno'):
            stack.enter_context(patch('app.messagebox.'+name,side_effect=lambda *a,**k:errors.append(str(a))))
        root=tk.Tk();root.withdraw();window=app.MainWindow(root)
        root.report_callback_exception=lambda *exc:errors.append(exc[0].__name__)
        window.diagnostic_mode.set(False);window.start();deadline=time.monotonic()+35
        def poll():
            store=window.subtitle_store
            if store:
                with store.lock:
                    cursor=store.db.execute('SELECT source,translated,translation_state,api_called FROM translation_jobs')
                    names=[c[0] for c in cursor.description]
                    rows=[dict(zip(names,r)) for r in cursor.fetchall()]
            else:rows=[]
            done=[r for r in rows if r['translation_state']=='completed']
            if done or time.monotonic()>deadline or errors:
                report.update(ok=bool(done) and not errors,rows=done,errors=errors,paid_api_calls=paid.call_count,
                    local_engine=window.local_coordinator.summary() if window.local_coordinator else None)
                window.close();return
            root.after(20,poll)
        root.after(20,poll);root.mainloop()
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['ok'] and report['paid_api_calls']==0 else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--python',required=True);p.add_argument('--model-path',required=True)
    p.add_argument('--device',choices=['cpu','cuda'],default='cpu');p.add_argument('--output',required=True)
    raise SystemExit(run(p.parse_args()))
