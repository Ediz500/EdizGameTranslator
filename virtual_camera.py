"""Raw OBS camera input; fail closed without saved AND live routing evidence."""
import json
import os
import re
import time
from pathlib import Path


class CaptureConfigurationError(ValueError):
    pass


def resolve_collection_path(obs,configured=''):
    """Prefer a previously chosen file; otherwise find the active standard collection."""
    if configured:return Path(configured)
    active=obs.client.get_scene_collection_list().current_scene_collection_name
    directory=Path(os.environ.get('APPDATA',''))/'obs-studio'/'basic'/'scenes'
    matches=[]
    for path in directory.glob('*.json'):
        try:
            if json.loads(path.read_text(encoding='utf-8')).get('name')==active:matches.append(path)
        except (ValueError,OSError):continue
    if len(matches)!=1:
        raise CaptureConfigurationError('OBS koleksiyonu bulunamadı. Ayarlar → Gelişmiş bölümünden aktif koleksiyon JSON dosyasını seçin.')
    return matches[0]


class RouteLog:
    """OBS logs unsaved VCam route changes. Incremental, read-only, fail closed.

    OBSBasic::UpdateVirtualCamConfig updates the live output but does not save
    the collection. The saved JSON alone is therefore insufficient proof.
    Unknown/partial route messages invalidate proof until a full supported line.
    """
    def __init__(self,path=None):
        self.directory=Path(os.environ.get('APPDATA',''))/'obs-studio'/'logs'
        self.path=Path(path) if path else None
        self.discover=path is None
        self.offset=0
        self.route=None
        self.partial=b''

    def check(self,source):
        try:
            if self.discover:
                latest=max(self.directory.glob('*.txt'),key=lambda p:p.stat().st_mtime_ns)
                if self.path is None:self.path=latest
                elif latest!=self.path:
                    raise CaptureConfigurationError('OBS yeniden başladı; kamera oturumunu yeniden başlatın.')
            size=self.path.stat().st_size
            if size<self.offset or size-self.offset>8_000_000:
                raise CaptureConfigurationError('OBS yönlendirme günlüğü değişti veya okunamıyor.')
            with self.path.open('rb') as stream:
                stream.seek(self.offset);chunk=stream.read()
            self.offset+=len(chunk)
            data=self.partial+chunk
            parts=data.split(b'\n');self.partial=parts.pop()
            for raw in parts:
                line=raw.decode('utf-8',errors='replace').rstrip('\r')
                if 'Virtual Camera output' in line:
                    match=re.fullmatch(r'.*?: (?:Starting|Changing) Virtual Camera output to Source : (.+)',line)
                    self.route=match.group(1) if match else None
                elif 'Virtual Camera Stop' in line:
                    self.route=None
            if self.partial or self.route!=source:
                raise CaptureConfigurationError('Canlı kamera yönü doğrulanamadı. OBS: Kaynak → ham PS5 girdisini seçip Sanal Kamera’yı yeniden başlatın.')
        except CaptureConfigurationError:raise
        except (OSError,ValueError,AttributeError):
            raise CaptureConfigurationError('OBS canlı yönlendirme günlüğü okunamadı; kamera güvenlik için kapalı.') from None


class LiveObsGuard:
    """Read-only live checks. Does not configure/start/stop OBS outputs."""
    def __init__(self,obs,route=None):
        self.obs=obs
        self.route=route or RouteLog()

    def __call__(self,collection,source):
        self.route.check(source)
        client=self.obs.client
        if client.get_scene_collection_list().current_scene_collection_name!=collection:
            raise CaptureConfigurationError('Seçili OBS koleksiyonu değişti. Doğru koleksiyonu açıp tekrar başlatın.')
        if not client.get_virtual_cam_status().output_active:
            raise CaptureConfigurationError('OBS Sanal Kamera kapalı. OBS’den Sanal Kamera’yı başlatın.')
        settings=client.get_input_settings(source)
        device=str(settings.input_settings.get('video_device_id','')).lower()
        if settings.input_kind!='dshow_input' or not device or 'obs' in device:
            raise CaptureConfigurationError('Yalnız ham capture card video girdisi kullanılabilir; sahne/ekran/OBS kamera girdisi reddedildi.')
        if any(f.get('filterEnabled',True) for f in client.get_source_filter_list(source).filters):
            raise CaptureConfigurationError('Ham oyun kaynağında etkin filtre var. Filtresiz capture card kaynağını seçin.')

    def close(self):
        self.obs.close()


def validate_raw_source_config(data, source):
    config=data.get('virtual-camera',{})
    # OBS VCamOutputType: Scene=1, Source=2, Program=3, Preview=4.
    if config.get('type2')!=2 or config.get('source')!=source:
        raise CaptureConfigurationError('OBS Virtual Camera must use Source output with the selected raw source')
    raw=next((s for s in data.get('sources',[]) if s.get('name')==source),None)
    if raw is None or raw.get('id')!='dshow_input':
        raise CaptureConfigurationError('Only a raw DirectShow capture-card source is permitted')
    if any(f.get('enabled',True) for f in raw.get('filters',[])):
        raise CaptureConfigurationError('Filtered sources are not allowed for virtual-camera OCR')
    if 'obs' in str(raw.get('settings',{}).get('video_device_id','')).lower():
        raise CaptureConfigurationError('Virtual-camera feedback input rejected')


def obs_camera_index():
    import comtypes
    comtypes.CoInitialize()
    try:
        from pygrabber.dshow_graph import FilterGraph
        devices=FilterGraph().get_input_devices()
    finally:
        comtypes.CoUninitialize()
    matches=[i for i,name in enumerate(devices) if name=='OBS Virtual Camera']
    if len(matches)!=1:
        raise CaptureConfigurationError('Exactly one named OBS Virtual Camera device is required')
    return matches[0]


class VirtualCamera:
    def __init__(self, config_path, source, width=1280, diagnostic=False, validator=None):
        if not diagnostic and not isinstance(validator,LiveObsGuard):
            raise CaptureConfigurationError('Canlı çeviri için OBS kaynak ve canlı yön denetimi zorunludur.')
        if width not in (960,1280,1920):
            raise CaptureConfigurationError('Unsupported virtual-camera width')
        import cv2
        self.cv2=cv2
        self.path=Path(config_path)
        self.source=source
        self.validator=validator
        self._config_signature=None;self._config_data=None
        self.last_timing={}
        self._check()
        # Do not try physical camera 0 or fall back to another video backend.
        self.cap=cv2.VideoCapture(obs_camera_index(),cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError('OBS Virtual Camera could not be opened')
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT,width*9//16)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE,1)  # Advisory only; continuous draining is the guarantee.

    def _check(self):
        began=time.perf_counter()
        stat=self.path.stat();signature=(stat.st_mtime_ns,stat.st_size,stat.st_ino)
        stated=time.perf_counter()
        reread=signature!=self._config_signature
        if reread:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            after=self.path.stat()
            if signature!=(after.st_mtime_ns,after.st_size,after.st_ino):
                raise CaptureConfigurationError('OBS koleksiyonu okuma sırasında değişti.')
            self._config_data=data;self._config_signature=signature
        data=self._config_data
        parsed=time.perf_counter()
        validate_raw_source_config(data,self.source)
        if self.validator:
            self.validator(data['name'],self.source)
        ended=time.perf_counter()
        return dict(config_stat_ms=(stated-began)*1000,config_read_parse_ms=(parsed-stated)*1000,
                    config_reread=reread,live_guard_ms=(ended-parsed)*1000)

    def read(self):
        pre=self._check()  # Live route and all WebSocket checks stay per-frame.
        began=time.perf_counter()
        ok,frame=self.cap.read()
        read=time.perf_counter()
        post=self._check()  # Discard if route changed during a blocking read.
        if not ok:
            raise RuntimeError('OBS Virtual Camera returned no frame')
        from PIL import Image
        self.last_timing=dict(pre=pre,post=post,camera_read_ms=(read-began)*1000)
        return Image.fromarray(self.cv2.cvtColor(frame,self.cv2.COLOR_BGR2RGB))

    def close(self):
        try:
            self.cap.release()
        finally:
            if self.validator:
                self.validator.close()
