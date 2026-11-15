"""Historical API-free screenshot benchmark ONLY; never imported by app.py."""
import base64
import io
from PIL import Image
from obs_capture import ObsSource


class LegacyObsSource(ObsSource):
    def frame(self,source_name):
        result=self.client.get_source_screenshot(source_name,'png',self.width,self.width*9//16,-1)
        return Image.open(io.BytesIO(base64.b64decode(result.image_data.split(',',1)[-1]))).convert('RGB')


class ScreenshotFrames:
    def __init__(self,obs,source):
        self.obs,self.source=obs,source

    def read(self):
        self.obs.validate_raw_source(self.source)
        return self.obs.frame(self.source)

    def close(self):
        self.obs.close()
