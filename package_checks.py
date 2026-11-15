"""Optional isolated packaged smoke test; uses temporary local settings and no cloud SDK."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch
from urllib.request import urlopen,Request
from PIL import Image,ImageDraw,ImageFont


def run(args):
    import app
    from core import DEFAULTS,load_settings,atomic_json
    from overlay_server import launch_server
    from region_profiles import with_region
    import cv2,comtypes,pygrabber,onnxruntime,rapidocr
    settings=load_settings() if args.real_camera else with_region(deepcopy(DEFAULTS),'Örnek Oyun',(0,.65,1,.94))
    password=app.secret_get('obs_password') if args.real_camera else ''
    report=dict(ok=False,frozen=bool(getattr(__import__('sys'),'frozen',False)),real_camera=args.real_camera,cloud_sdk_loaded=False)
    synthetic=Image.new('RGB',(960,540),'#24374d');draw=ImageDraw.Draw(synthetic)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
    draw.text((210,400),'Scout: Stay close. We are almost there.',font=font,fill='white')
    count=[0];original=app.MainWindow._make_capture_source
    class FakeCamera:
        def read(self):time.sleep(.025);return synthetic
        def close(self):pass
    def capture(window,s):
        count[0]+=1
        return original(window,s) if args.real_camera else FakeCamera()
    with ExitStack() as stack:
        folder=Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(patch('app.load_settings',return_value=deepcopy(settings)))
        for target in ('app.config_folder','core.config_folder'):stack.enter_context(patch(target,return_value=folder))
        stack.enter_context(patch('app.secret_get',side_effect=lambda k:password if k=='obs_password' else ''))
        stack.enter_context(patch('app.secret_save'))
        stack.enter_context(patch.object(app.MainWindow,'_make_capture_source',capture))
        stack.enter_context(patch('app.launch_server',side_effect=lambda state:launch_server(state,0)))
        root=tk.Tk();window=app.MainWindow(root)
        errors=[];root.report_callback_exception=lambda *exc:errors.append(exc[0].__name__)
        window.show_desktop.set(False)
        if not args.real_camera:window.source.set('Synthetic raw input')
        window.diagnostic_mode.set(True);window.start()
        deadline=time.monotonic()+30;stage=[0];editor=[None];packets=set()
        def finish():
            report.update(camera_opens=count[0],tk_errors=errors,cloud_sdk_loaded=any(n=='openai' or n.startswith('openai.') for n in __import__('sys').modules))
            window.close()
        def poll():
            if time.monotonic()>deadline:
                report['timeout']=True;finish();return
            if not window.running:
                report['capture_stopped']=True;finish();return
            if stage[0]==0 and window.capture_feed and window.capture_feed.peek():
                window.open_region_editor();editor[0]=window.region_editor;stage[0]=1
            e=editor[0]
            if stage[0]==1 and e and e.packet:
                packets.add(e.packet.sequence)
                if len(packets)>=2:e.test_ocr();stage[0]=2
            if stage[0]==2 and not e.in_test:
                report['local_ocr_completed']=e.result is not None
                report['ocr_lines']=len(e.result['texts']) if e.result else 0
                report['editor_opened']=e.window.winfo_viewable()==1
                e.cancel();report['capture_survived_editor_close']=window.running
                store=window.subtitle_store;session=window.active_capture_settings['_capture_session'];now=time.monotonic()
                examples=[('Scout','Köprüye birlikte ulaşabiliriz. Yakınımda kal.'),('Pilot','Önümüzde iki devriye var. Sessizce geçmeliyiz.'),
                          ('Scout','Tamam, sen yolu göster. Arkandan geliyorum.'),('Pilot','Hazır olduğunda hareket edelim.')]
                for speaker,text in examples:
                    row=store.accept(session,'Synthetic test line',now,now,time.time(),now,.99,'package_test',speaker=speaker)
                    job=store.enqueue_translation(session,row,'Synthetic test line','local:fixture',now)
                    store.complete_translation(job,text,now)
                port=window.server.server_port
                with urlopen(f'http://127.0.0.1:{port}/state') as response:state=json.load(response)
                report['overlay_blocks']=len(state['blocks']);report['waiting']=state['waiting']
                # Protocol smoke only; real-browser DOM evidence is tested separately.
                body=json.dumps(dict(ids=[b['id'] for b in state['blocks']],generation=state['generation'])).encode()
                if args.overlay_image and not args.real_camera:
                    chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
                    result=subprocess.run([str(chrome),'--headless=new','--disable-gpu','--no-first-run','--hide-scrollbars',
                        '--force-device-scale-factor=1','--window-size=1920,1080','--default-background-color=182435ff',
                        '--user-data-dir='+str(folder/'browser'),'--screenshot='+str(Path(args.overlay_image).resolve()),
                        '--virtual-time-budget=1200',f'http://127.0.0.1:{port}/overlay'],capture_output=True,timeout=25,creationflags=0x08000000)
                    report['browser_image_created']=Path(args.overlay_image).exists() and result.returncode==0
                    report['browser_reported_dom_visible']=store.db.execute('SELECT count(*) FROM translation_jobs WHERE visible_mono IS NOT NULL').fetchone()[0]
                with urlopen(Request(f'http://127.0.0.1:{port}/ack',data=body,headers={'Content-Type':'application/json'})) as response:
                    report['http_ack_status']=response.status
                report['ok']=bool(report['local_ocr_completed'] and report['editor_opened'] and report['overlay_blocks']==3 and report['waiting']==1 and not errors)
                finish();return
            root.after(80,poll)
        root.after(100,poll);root.mainloop()
        report['workers_closed']=all(not worker.is_alive() for worker in window.workers)
        assert not report['cloud_sdk_loaded']
    if getattr(args,'local_model',None):
        from light_translation import WarmNMTClient
        client=WarmNMTClient(args.local_python,args.local_model,device=args.local_device,
            compute_type='int8_float16' if args.local_device=='cuda' else 'int8',
            workers=1,threads=2,beam_size=4)
        try:
            answer=client.translate('You must not open the door.')
            report['packaged_local_model']=dict(text=answer['text'],complete=answer['complete'],
                runtime=client.ready['runtime'],roundtrip_ms=answer['roundtrip_ms'])
            report['ok']=report['ok'] and answer['complete']
        finally:client.close()
        report['local_worker_closed']=client.process.poll() is not None
    atomic_json(Path(args.report).resolve(),report)
    print(json.dumps(report,indent=2))
