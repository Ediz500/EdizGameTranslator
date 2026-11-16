"""Isolated synthetic UI review. Never reads/writes real settings, vault or OBS."""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
import customtkinter as ctk
from PIL import Image,ImageDraw,ImageFont
from ediz_game_translator import app
from ediz_game_translator.core import DEFAULTS
from ediz_game_translator.subtitles.overlay_server import launch_server


def main():
    p=argparse.ArgumentParser();p.add_argument('--scale',type=float,default=1);p.add_argument('--seconds',type=int,default=600)
    p.add_argument('--three',action='store_true')
    a=p.parse_args();ctk.set_appearance_mode('dark');ctk.set_widget_scaling(a.scale);ctk.set_window_scaling(a.scale)
    with ExitStack() as stack:
        folder=Path(stack.enter_context(tempfile.TemporaryDirectory()))
        settings=deepcopy(DEFAULTS);settings['game']='Örnek Oyun';settings['show_desktop']=False
        stack.enter_context(patch('ediz_game_translator.app.load_settings',return_value=settings))
        for target in ('ediz_game_translator.app.config_folder','ediz_game_translator.core.config_folder'):stack.enter_context(patch(target,return_value=folder))
        stack.enter_context(patch('ediz_game_translator.app.secret_get',return_value=''))
        stack.enter_context(patch('ediz_game_translator.app.secret_save'))
        stack.enter_context(patch('ediz_game_translator.app.launch_server',side_effect=lambda state:launch_server(state,0)))
        root=ctk.CTk();w=app.MainWindow(root);root.title(f'Ediz UI İnceleme · Sentetik · {a.scale:.2f}')
        scene=Image.new('RGB',(1920,1080),'#172636');d=ImageDraw.Draw(scene)
        d.polygon([(0,700),(450,240),(920,700),(1450,180),(1920,600),(1920,1080),(0,1080)],fill='#2D465B')
        font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',40)
        d.text((60,55),'ÖRNEK SAHNE — gerçek oyun kaydı değildir',font=font,fill='#8F9CB0')
        w.preview_active=True;w.capture_feed=SimpleNamespace(peek=lambda:SimpleNamespace(image=scene,sequence=1),error=None)
        w.connection_var.set('Görsel inceleme · OBS ve model bağlantısı kurulmadı')
        w.status_var.set('Sentetik önizleme · gerçek donanım testi değildir')
        w.overlay_state.set('Onlar gelmeden buradan ayrılmalıyız.',a.seconds)
        store=w.overlay_state.manager.store;store.db.execute("UPDATE live_sources SET speaker='Scout'")
        w.last_source_var.set('Scout: We should leave before they arrive.')
        w.last_translation_var.set('Onlar gelmeden buradan ayrılmalıyız. · Örnek')
        if a.three:
            now=time.monotonic();entries=[]
            for i,(speaker,text) in enumerate([('Scout','Yakınımda kal. Köprüye birlikte ulaşabiliriz.'),('Pilot','Önümüzde iki devriye var.'),('','Hazır olduğunda hareket edelim.')]):
                source='Synthetic source '+str(i)
                row=store.accept('manual',source,now,now,0,now,.99,'fixture',speaker=speaker)
                entries.append(dict(subtitle_id=row,track_key=str(row),canonical=source,speaker=speaker,bounds=[.15,.25+i*.22,.85,.32+i*.22],manual_until=now+a.seconds))
                job=store.enqueue_translation('manual',row,source,'local:fixture',now);store.complete_translation(job,text,now)
            old=[r[0] for r in store.db.execute('SELECT track_key FROM live_sources WHERE active=1')]
            store.publish_sources('manual',entries,now,retired=old)
        print('browser_preview=http://127.0.0.1:'+str(w.server.server_port)+'/overlay',flush=True)
        root.after(a.seconds*1000,w.close);root.mainloop()


if __name__=='__main__':main()
