"""Render our real Tk editor with a synthetic frame and local OCR; no camera/API."""
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from PIL import Image,ImageDraw,ImageFont,ImageGrab
from ediz_game_translator.capture.frame_sources import FramePacket
from ediz_game_translator.ui.region_editor import RegionEditor
from ediz_game_translator.capture.preview_service import SharedOCR
from ediz_game_translator.capture.ocr_profiles import create_ocr


def main():
    import ctypes
    try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:pass
    image=Image.new('RGB',(1920,1080),'#22374a');d=ImageDraw.Draw(image)
    d.rectangle((0,560,1920,1080),fill='#18242e')
    for i,h in enumerate((210,320,180,430,290,350,190,280)):
        x=40+i*250
        d.rectangle((x,560-h,x+180,560),fill='#2d4554')
        for y in range(560-h+30,530,50):
            d.rectangle((x+25,y,x+155,y+12),fill='#526472')
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',42)
    d.text((960,840),'Scout: Stay close.',font=font,anchor='mm',fill='white')
    d.text((960,900),'We are almost there.',font=font,anchor='mm',fill='white')
    small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',26)
    d.text((60,60),'SYNTHETIC TEST FRAME - NOT A REAL GAME',font=small,fill='#9bb5c5')
    root=tk.Tk();root.title('Editor preview');root.geometry('180x40+20+20')
    packet=FramePacket(image,1,time.perf_counter(),time.time(),0)
    service=SharedOCR(lambda:create_ocr('bounded960_cpu2'))
    threads=[]
    def spawn(fn):
        worker=threading.Thread(target=fn);threads.append(worker);worker.start()
    editor=RegionEditor(root,'Örnek Oyun · sentetik görüntü',(0,.65,1,.94),lambda:(packet,'Sentetik test karesi'),
                        lambda:service,spawn,lambda rect:None,root.destroy)
    editor.window.geometry('1040x780+180+70')
    deadline=time.monotonic()+15
    def begin():
        if editor.packet is None:root.after(100,begin);return
        editor.test_ocr();root.after(100,check)
    def capture():
        w=editor.window
        box=(w.winfo_rootx(),w.winfo_rooty(),w.winfo_rootx()+w.winfo_width(),w.winfo_rooty()+w.winfo_height())
        ImageGrab.grab(bbox=box).save('REGION_EDITOR_PREVIEW.png')
        print('Real Tk editor captured; local OCR lines:',len(editor.result['texts']) if editor.result else 0)
        editor.close()
    def check():
        if editor.result is not None or time.monotonic()>deadline:
            editor.window.lift();editor.window.attributes('-topmost',True)
            root.after(250,capture)
        else:root.after(100,check)
    root.after(150,begin);root.mainloop()
    for worker in threads:worker.join()


if __name__=='__main__':main()
