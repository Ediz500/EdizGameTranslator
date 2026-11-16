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
    from ediz_game_translator import app
    from ediz_game_translator.core import DEFAULTS,load_settings,atomic_json
    from ediz_game_translator.subtitles.overlay_server import launch_server
    from ediz_game_translator.storage.region_profiles import with_region
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
        stack.enter_context(patch('ediz_game_translator.app.load_settings',return_value=deepcopy(settings)))
        for target in ('ediz_game_translator.app.config_folder','ediz_game_translator.core.config_folder'):stack.enter_context(patch(target,return_value=folder))
        stack.enter_context(patch('ediz_game_translator.app.secret_get',side_effect=lambda k:password if k=='obs_password' else ''))
        stack.enter_context(patch('ediz_game_translator.app.secret_save'))
        stack.enter_context(patch.object(app.MainWindow,'_make_capture_source',capture))
        stack.enter_context(patch('ediz_game_translator.app.launch_server',side_effect=lambda state:launch_server(state,0)))
        import customtkinter as ctk
        root=ctk.CTk();window=app.MainWindow(root)
        errors=[]
        def callback_error(*exc):
            errors.append(exc[0].__name__);report['callback_error']=exc[0].__name__;finish()
        root.report_callback_exception=callback_error
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
                window.stop()
                store=window.subtitle_store;session='package_fixture';now=time.monotonic()
                window.overlay_state.bind(store,session,live=True)
                examples=[('Scout','Köprüye birlikte ulaşabiliriz. Yakınımda kal.'),('Pilot','Önümüzde iki devriye var. Sessizce geçmeliyiz.'),
                          ('Scout','Tamam, sen yolu göster. Arkandan geliyorum.'),('Pilot','Hazır olduğunda hareket edelim.')]
                entries=[]
                for i,(speaker,text) in enumerate(examples[:3]):
                    row=store.accept(session,'Synthetic test line',now,now,time.time(),now,.99,'package_test',speaker=speaker)
                    entries.append(dict(subtitle_id=row,track_key='package_'+str(i),canonical='Synthetic test line',speaker=speaker,bounds=[.15,.25+i*.22,.85,.32+i*.22]))
                    job=store.enqueue_translation(session,row,'Synthetic test line','local:fixture',now)
                    store.complete_translation(job,text,now)
                store.publish_sources(session,entries,now)
                store.enable_live_session(session,stale=2)
                port=window.server.server_port
                with urlopen(f'http://127.0.0.1:{port}/state') as response:state=json.load(response)
                report['overlay_blocks']=len(state['blocks']);report['waiting']=state['waiting']
                # Protocol smoke only; real-browser DOM evidence is tested separately.
                body=json.dumps(dict(ids=[b['id'] for b in state['blocks']],generation=state['generation'])).encode()
                if args.overlay_image and not args.real_camera:
                    chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
                    alive=threading.Event()
                    def refresh():
                        while not alive.wait(.1):store.publish_sources(session,entries,time.monotonic())
                    keep=threading.Thread(target=refresh,daemon=True);keep.start()
                    try:
                        result=subprocess.run([str(chrome),'--headless=new','--disable-gpu','--no-first-run','--hide-scrollbars',
                        '--force-device-scale-factor=1','--window-size=1920,1080','--default-background-color=182435ff',
                        '--user-data-dir='+str(folder/'browser'),'--screenshot='+str(Path(args.overlay_image).resolve()),
                        '--virtual-time-budget=1200',f'http://127.0.0.1:{port}/overlay'],capture_output=True,timeout=25,creationflags=0x08000000)
                    finally:
                        alive.set();keep.join(timeout=2)
                    report['browser_image_created']=Path(args.overlay_image).exists() and result.returncode==0
                    report['browser_reported_dom_visible']=store.db.execute('SELECT count(*) FROM translation_jobs WHERE visible_mono IS NOT NULL').fetchone()[0]
                with urlopen(Request(f'http://127.0.0.1:{port}/ack',data=body,headers={'Content-Type':'application/json'})) as response:
                    report['http_ack_status']=response.status
                report['ok']=bool(report['local_ocr_completed'] and report['editor_opened'] and report['overlay_blocks']==3 and report['waiting']==0 and not errors)
                finish();return
            root.after(80,poll)
        root.after(100,poll);root.mainloop()
        report['workers_closed']=all(not worker.is_alive() for worker in window.workers)
        assert not report['cloud_sdk_loaded']
    if getattr(args,'local_model',None):
        from ediz_game_translator.translation.light_translation import WarmNMTClient
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
