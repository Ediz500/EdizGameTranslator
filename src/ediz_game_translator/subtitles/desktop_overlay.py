"""Windows-only, click-through caption that follows a selected monitor."""
from __future__ import annotations

import sys
import tkinter as tk

KEY_COLOR = "#ff00ff"


def monitors():
    from screeninfo import get_monitors
    return list(get_monitors())


class DesktopOverlay:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.configure(bg=KEY_COLOR)
        self.window.wm_attributes("-transparentcolor", KEY_COLOR)
        self.window.wm_attributes("-topmost", True)
        self.canvas = tk.Canvas(self.window, bg=KEY_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.width = 1920
        self.height = 1080
        self.font = 36
        self.bottom = 10
        self._previous = None
        self.enabled = False

    def show(self, screen, font=36, bottom=10):
        self.width = int(screen.width)
        self.height = int(screen.height)
        self.font = font
        self.bottom = bottom
        self.window.geometry(f"{self.width}x{self.height}+0+0")
        self.window.deiconify()
        self.window.update_idletasks()
        if sys.platform == "win32":
            import ctypes
            # Tk on Windows can wrap the inner widget in a native top-level HWND.
            user = ctypes.windll.user32
            user.GetParent.argtypes = [ctypes.c_void_p]
            user.GetParent.restype = ctypes.c_void_p
            user.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            user.SetWindowPos.restype = ctypes.c_bool
            inner_hwnd = self.window.winfo_id()
            hwnd = user.GetParent(inner_hwnd) or inner_hwnd
            # Make overlay non-focusable; mouse and controller input pass through.
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x20
            WS_EX_LAYERED = 0x80000
            WS_EX_NOACTIVATE = 0x08000000
            if ctypes.sizeof(ctypes.c_void_p) == 8:
                user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
                user.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
                user.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
                existing = user.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                user.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, existing | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE)
            else:
                old = user.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user.SetWindowLongW(hwnd, GWL_EXSTYLE, old | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE)
            # SetWindowPos uses real virtual-display coordinates, including negative monitor positions.
            user.SetWindowPos(hwnd, -1, int(screen.x), int(screen.y), self.width, self.height, 0x0010)
        self.enabled = True
        self._previous = None

    def render(self, text: str):
        self.render_blocks([dict(text=text,speaker='')] if text else [])

    def render_blocks(self,blocks,style=None):
        from ediz_game_translator.subtitles.canvas_view import draw_captions
        from ediz_game_translator.storage.subtitle_styles import DEFAULT_STYLE
        style=style or dict(DEFAULT_STYLE,font_size=self.font)
        from ediz_game_translator.subtitles.layout import visual_signature
        signature=repr((visual_signature(blocks),style,self.width,self.height))
        if not self.enabled or self._previous == signature:return
        self._previous=signature
        draw_captions(self.canvas,blocks,style,self.width,self.height)

    def hide(self):
        self.enabled = False
        self.window.withdraw()
        self._previous = None

    def destroy(self):
        self.window.destroy()
