"""Read-only localhost OBS metadata and crop geometry. No screenshot OCR path."""
from __future__ import annotations

import time
from PIL import Image


class ObsSource:
    def __init__(self, password: str, port: int = 4455, width: int = 1920):
        if width not in (1920,1280,960):
            raise ValueError('Screenshot width must be 1920, 1280 or 960')
        self.width = width
        self._validated = None
        import obsws_python as obs
        # Only localhost, no connections exposed over public Wi-Fi or Internet.
        self.client = obs.ReqClient(host="127.0.0.1", port=port, password=password, timeout=5)

    def list_inputs(self) -> list[str]:
        result = self.client.get_input_list()
        names = [obj.get("inputName", "") for obj in result.inputs]
        return sorted(n for n in names if n)

    def close(self):
        self.client.disconnect()

    def validate_raw_source(self,source_name):
        """Reject composited/feedback sources before publishing any preview frame."""
        from ediz_game_translator.capture.virtual_camera import CaptureConfigurationError
        if self._validated and self._validated[0]==source_name and time.perf_counter()-self._validated[1]<.5:return
        result=self.client.get_input_settings(source_name)
        kind=result.input_kind
        settings=result.input_settings
        if kind not in ('dshow_input','game_capture','window_capture'):
            raise CaptureConfigurationError('OCR requires a raw capture-card/game/window source, never Browser/Scene/Display')
        if kind=='dshow_input' and 'obs' in str(settings.get('video_device_id','')).casefold():
            raise CaptureConfigurationError('OBS camera input would create a feedback loop')
        if kind=='window_capture':
            target=str(settings.get('window','')).casefold()
            if not target or any(x in target for x in ('obs64.exe','obs32.exe','python.exe','pythonw.exe','edizgametranslator')):
                raise CaptureConfigurationError('OBS/translator windows are not raw game inputs')
        if any(f.get('filterEnabled',True) for f in self.client.get_source_filter_list(source_name).filters):
            raise CaptureConfigurationError('Filtered source cannot be verified as raw OCR input')
        self._validated=(source_name,time.perf_counter())

def crop_frame(frame: Image.Image, left: float, top: float, right: float, bottom: float) -> Image.Image:
    w, h = frame.size
    if not 0 <= left < right <= 100 or not 0 <= top < bottom <= 100:
        raise ValueError("Kırpma koordinatları 0-100 aralığında, sol < sağ ve üst < alt olmalı.")
    return frame.crop((int(w * left / 100), int(h * top / 100),
                       int(w * right / 100), int(h * bottom / 100)))
