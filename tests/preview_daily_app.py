"""Capture actual Windows Tk pages with isolated settings and empty credentials."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from unittest.mock import patch
from PIL import ImageGrab
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from core import DEFAULTS
from region_profiles import with_region


def main():
    import ctypes
    try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:pass
    settings=with_region(deepcopy(DEFAULTS),'Örnek Oyun',(0.12,.64,.88,.94))
    with tempfile.TemporaryDirectory() as folder,patch('app.load_settings',return_value=settings),\
            patch('app.config_folder',return_value=Path(folder)),patch('core.config_folder',return_value=Path(folder)),\
            patch('app.secret_get',return_value=''),patch('app.secret_save'),patch('app.WarmNMTClient') as api:
        root=tk.Tk();w=app.MainWindow(root);root.geometry('1120x840+120+80')
        root.attributes('-topmost',True)
        def capture(name):
            root.update_idletasks()
            print(name,'page',w.current_page,'scroll',w.pages[w.current_page].canvas.canvasy(0),
                  'body',w.pages[w.current_page].body.winfo_y())
            box=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())
            ImageGrab.grab(bbox=box).save(name)
        def home():
            capture('DAILY_HOME.png');w.show_page('Ayarlar');root.after(250,settings_top)
        def settings_top():
            capture('DAILY_SETTINGS.png')
            w.pages['Ayarlar'].canvas.yview_moveto(1);root.after(250,settings_bottom)
        def settings_bottom():
            capture('DAILY_SETTINGS_BOTTOM.png');w.close()
        root.after(350,home);root.mainloop();api.assert_not_called()
    print('Three real Windows Tk screenshots captured. No camera or API opened.')


if __name__=='__main__':main()
