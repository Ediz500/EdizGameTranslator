"""Ediz Game Translator v0.1 (Windows) — OBS source -> OCR -> AI -> OBS + monitor."""
from __future__ import annotations

import queue
import uuid
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from core import (BudgetLedger, ContextMemory, PRICE_PER_MILLION, SubtitleTimeline,
                  TranslationEngine,
                  load_settings, save_settings, config_folder)
from desktop_overlay import DesktopOverlay, monitors
from obs_capture import ObsSource, crop_frame
from capture_pipeline import CaptureRunner, DiagnosticLog
from subtitle_store import SubtitleStore
from frame_sources import LatestFrames
from ocr_profiles import create_ocr
from virtual_camera import VirtualCamera, LiveObsGuard, CaptureConfigurationError,resolve_collection_path
from overlay_server import SharedOverlayState, launch_server
from region_editor import RegionEditor
from region_profiles import region_for,with_region,CROP_KEYS,game_key
from region_geometry import DEFAULT_REGION
from preview_service import SharedOCR
from image_change import ImageChangeGate
from light_translation import WarmNMTClient,model_manifest,validate_capacity
from translation_dispatch import LocalTranslationCoordinator

APP_TITLE = "Ediz Game Translator · v0.1"
OBS_OVERLAY_URL = "http://127.0.0.1:8788/overlay"
SERVICE = "EdizGameTranslator-V01"


def secret_get(name: str) -> str:
    try:
        import keyring
        return keyring.get_password(SERVICE, name) or ""
    except Exception:
        return ""


def secret_save(name: str, value: str) -> None:
    import keyring
    if value:
        keyring.set_password(SERVICE, name, value)
    else:
        try:
            keyring.delete_password(SERVICE, name)
        except Exception:
            pass


class MainWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("875x930")
        root.minsize(790, 700)
        self.settings = load_settings()
        self.ledger = BudgetLedger(self.settings["estimated_total_usd"],
                                   self.settings["usd_try"], self.settings["budget_try"],
                                   path=config_folder() / "ledger.json",
                                   initial_in=self.settings['token_total_in'],
                                   initial_out=self.settings['token_total_out'])
        self.overlay_state = SharedOverlayState()
        self.overlay_state.transport=self.settings.get('display_transport','poll')
        self.overlay = DesktopOverlay(root)
        self.server = None
        self.running = False
        self.closing = False
        self.workers = []
        self.stop_evt = threading.Event()
        self.events: queue.Queue = queue.Queue()
        self.timeline = SubtitleTimeline()
        self.start_at = time.monotonic()
        self.seq = 0
        self.latest_seq = 0
        self.session_id = 0
        self.monitors_list = []
        self.capture_lock = threading.Lock()
        self.subtitle_store = None
        self.diagnostic_active = False
        self.region_editor = None
        self.capture_feed = None
        self.shared_ocr = None
        self.preview_stop = None
        self.preview_active = False
        self.preview_status = 'Kaynak hazırlanıyor…'
        self.session_initial_usd = self.ledger.usd
        self.shown_ids=set()
        self.close_after=None
        self.metrics_saved_session=None
        self.local_coordinator=None
        self._make_ui()
        self.game.trace_add('write',self._load_game_region)
        self._load_game_region()
        self._populate_monitors()
        try:
            self.server = launch_server(self.overlay_state)
            self.log("OBS altyazı sunucusu hazır: " + OBS_OVERLAY_URL)
        except OSError as exc:
            self.log(f"HATA: 8788 portu açılamadı: {exc}")
            messagebox.showwarning("OBS katmanı", "8788 portu kullanımda. Önce diğer uygulamayı kapat.")
        self.pump_after = self.root.after(20, self.pump)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _make_ui(self):
        from app_ui import build_ui
        self._get_secret=secret_get
        build_ui(self)

    def toggle_translation(self):
        if self.running:self.stop()
        else:self.start()

    def open_overlay(self):
        webbrowser.open(OBS_OVERLAY_URL)

    def save_preferences(self):
        if self.prepare(require_source=False,require_key=False):
            self.status_var.set('Ayarlar kaydedildi. Görüntü ayarları sonraki başlangıçta uygulanır.')

    def forget_api_key(self):
        if self.running or any(w.is_alive() for w in self.workers):
            messagebox.showinfo('API anahtarı','Anahtarı silmeden önce oturumu durdurun ve işlemlerin bitmesini bekleyin.')
            return
        try:
            secret_save('openai_api_key','')
            self.api_key.set('')
            self.status_var.set('API anahtarı Windows kasasından silindi.')
        except Exception:
            messagebox.showerror('API anahtarı','Windows anahtar kasası güncellenemedi. Tekrar deneyin.')

    def _change_game(self,new_name,rename=False):
        if self.running or self.region_editor is not None or any(w.is_alive() for w in self.workers):
            raise ValueError('Oyun profilini değiştirmeden önce oturumu ve OCR düzenleyicisini kapatın.')
        from region_profiles import rename_game,game_names
        if rename:
            updated=rename_game(self.settings,self.game.get(),new_name)
        else:
            if game_key(new_name) in {game_key(n) for n in game_names(self.settings)}:
                raise ValueError('Bu adda bir oyun zaten var.')
            updated=with_region(self.settings,new_name,DEFAULT_REGION)
        save_settings(updated)
        self.settings=updated
        self.game_combo['values']=game_names(updated)
        self.game.set(updated['game'])

    def add_game(self):
        name=simpledialog.askstring('Yeni oyun','Oyun adı:',parent=self.root)
        if name is None:return
        try:self._change_game(name)
        except (ValueError,OSError) as exc:messagebox.showerror('Oyun profili',str(exc))

    def rename_game(self):
        name=simpledialog.askstring('Oyun adını değiştir','Yeni oyun adı:',initialvalue=self.game.get(),parent=self.root)
        if name is None:return
        try:self._change_game(name,rename=True)
        except (ValueError,OSError) as exc:messagebox.showerror('Oyun profili',str(exc))

    def _load_game_region(self,*_):
        if not self.game.get().strip():return
        try:rect=region_for(self.settings,self.game.get())
        except ValueError:rect=DEFAULT_REGION
        for key,value in zip(CROP_KEYS,rect):self.crop_vars[key].set(str(value*100))
        self._region_summary()

    def _region_summary(self):
        values=[float(self.crop_vars[k].get()) for k in CROP_KEYS]
        self.crop_summary.set('Oyuna özel alan hazır · Görsel olarak düzenle')
        if hasattr(self,'region_canvas'):
            c=self.region_canvas;c.delete('all')
            c.create_rectangle(4,4,156,86,fill='#24374d',outline='')
            l,t,r,b=[x/100 for x in values]
            c.create_rectangle(4+l*152,4+t*82,4+r*152,4+b*82,fill='#365b68',outline='#64d8c0',width=2)

    def _make_capture_source(self,s):
        source_obs=self._obs(s)
        try:
            path=resolve_collection_path(source_obs,s.get('camera_config',''))
            return VirtualCamera(path,s['obs_source'],s.get('capture_width',960),
                diagnostic=s.get('_diagnostic',False),validator=LiveObsGuard(source_obs))
        except Exception:
            source_obs.close();raise

    def _preview_packet(self):
        feed=self.capture_feed
        if feed is None:return None,self.preview_status
        if feed.error is not None:return None,'Kaynak hatası: '+type(feed.error).__name__
        packet=feed.peek()
        if packet is None:return None,'Ham kare bekleniyor…'
        return packet,f'{packet.image.width} × {packet.image.height} · Hedef 1–2 FPS'

    def _preview_worker(self,s,stop):
        buffered=None;service=None
        if not self.capture_lock.acquire(blocking=False):return
        try:
            service=SharedOCR(lambda:create_ocr(s['ocr_profile']))
            self.shared_ocr=service
            buffered=LatestFrames(lambda:self._make_capture_source(s),stop,
                period=0)
            self.capture_feed=buffered
            while not stop.wait(.1):
                if buffered.error is not None:raise RuntimeError('Preview capture failed') from buffered.error
        except Exception as exc:
            cause=exc.__cause__ or exc
            self.preview_status=str(cause) if isinstance(cause,CaptureConfigurationError) else 'Önizleme açılamadı: '+type(exc).__name__
        finally:
            try:
                if buffered is not None:buffered.close()
            finally:
                if self.capture_feed is buffered:self.capture_feed=None
                if self.shared_ocr is service:self.shared_ocr=None
                self.capture_lock.release()

    def open_region_editor(self):
        if self.closing:return
        if self.region_editor is not None:
            self.region_editor.window.lift();return
        if not self.running and any(w.is_alive() for w in self.workers):
            self.status_var.set('Önceki işlemin bitmesi bekleniyor; yeni kamera açılmadı.');return
        try:
            game=self.game.get().strip() or 'Genel oyun'
            game_key(game)
            rect=tuple(float(self.crop_vars[k].get())/100 for k in CROP_KEYS)
            owned_stop=None
            if not self.running:
                s=dict(obs_port=int(self.obs_port.get()),obs_source=self.source.get().strip(),
                    obs_password_runtime=self.obs_password.get(),capture_method='virtual_camera',
                    capture_width=int(self.capture_width.get()),ocr_profile=self.ocr_profile.get(),
                    camera_config=self.camera_config.get(),_diagnostic=True)
                if not s['obs_source']:raise ValueError('Önce ham oyun kaynağını seç.')
                owned_stop=threading.Event();self.preview_stop=owned_stop
                self.preview_active=True;self.preview_status='Önizleme kaynağı hazırlanıyor…'
                self.overlay_state.clear();self.overlay.hide()
                self._spawn(self._preview_worker,s,owned_stop)
            def save(rect):
                if game_key(self.game.get())!=game_key(game):
                    raise ValueError('Oyun profili değişti; iptal edip doğru profil için editörü aç.')
                settings=with_region(self.settings,game,rect)
                save_settings(settings)  # Commit before changing any live UI/settings.
                self.settings=settings
                for key,value in zip(CROP_KEYS,rect):self.crop_vars[key].set(str(value*100))
                self._region_summary()
                self.status_var.set('OCR alanı oyun profiline kaydedildi. Aktif oturuma sonraki başlangıçta uygulanır.')
            def closed():
                if owned_stop is not None:owned_stop.set()
                self.preview_active=False
                self.region_editor=None
            cached_service=[self.shared_ocr]
            def preview():
                if self.shared_ocr is not None:cached_service[0]=self.shared_ocr
                return self._preview_packet()
            self.region_editor=RegionEditor(self.root,game,rect,preview,
                lambda:self.shared_ocr or cached_service[0],self._spawn,save,closed)
        except Exception as exc:
            if self.preview_stop is not None:self.preview_stop.set()
            self.preview_active=False
            self.status_var.set('OCR düzenleyici: '+str(exc))

    def _choose_camera_config(self):
        selected=filedialog.askopenfilename(title='OBS Source sanal kamera ayarını içeren koleksiyon',filetypes=[('OBS collection','*.json')])
        if selected:
            self.camera_config.set(selected)

    def _populate_monitors(self):
        try:
            self.monitors_list = monitors()
        except Exception as exc:
            self.log("Monitörler okunamadı: " + type(exc).__name__)
        if not self.monitors_list:
            return
        self.monitor_combo["values"] = [f"{i + 1}: {m.width}x{m.height} ({m.x},{m.y})"
                                        for i, m in enumerate(self.monitors_list)]
        self.monitor_combo.current(min(max(int(self.settings["monitor_index"]), 0), len(self.monitors_list)-1))

    def log(self, msg: str):
        self.log_box.configure(state="normal")
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{stamp}] {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _spawn(self, target, *args):
        if self.closing:
            return
        self.workers = [w for w in self.workers if w.is_alive()]
        worker = threading.Thread(target=target, args=args, daemon=False)
        self.workers.append(worker)
        worker.start()

    def post_session(self, session_id, kind, *args):
        self.post('session', session_id, kind, args)

    def post(self, kind, *args):
        self.events.put((kind, args))

    def _settings_from_ui(self):
        s = dict(self.settings)
        s.update(obs_port=int(self.obs_port.get().strip()),
                 obs_source=self.source.get().strip(),
                 model=self.model.get(), game=self.game.get().strip() or "Genel oyun",
                 lore=self.lore_text.get("1.0", "end").strip(),
                 budget_try=float(self.budget.get().replace(",", ".")),
                 usd_try=float(self.usd_try.get().replace(",", ".")),
                 scan_interval=float(self.interval.get().replace(",", ".")),
                 monitor_index=max(self.monitor_combo.current(), 0),
                 show_desktop=bool(self.show_desktop.get()),
                 font_size=int(self.font_var.get()),
                 overlay_bottom=int(self.bottom_var.get()))
        s.update(capture_method='virtual_camera',capture_width=int(self.capture_width.get()),
                 ocr_profile=self.ocr_profile.get(),camera_config=self.camera_config.get())
        s.update(translation_engine=self.local_engine.get(),local_python=self.local_python.get().strip() or
                 (sys.executable if not getattr(sys,'frozen',False) else ''),
                 local_model_path=self.local_model_path.get().strip(),local_device=self.local_device.get(),
                 local_compute_type=self.local_compute.get(),local_workers=int(self.local_workers.get()),
                 local_threads=int(self.local_threads.get()),capture_schedule=self.capture_schedule.get())
        validate_capacity(s['local_workers'],s['local_threads'],s['local_device'])
        if s['translation_engine'] not in ('ct2-marian','argos-ct2'):raise ValueError('Yerel motor seçin.')
        if s['capture_width'] not in (1920,1280,960):
            raise ValueError('Yakalama yöntemi/çözünürlük geçersiz.')
        if s['ocr_profile'] not in ('baseline','bounded960','bounded1280','bounded960_cpu2','mobile_en'):
            raise ValueError('OCR profili geçersiz.')
        for k, v in self.crop_vars.items():
            s[k] = float(v.get().replace(",", "."))
        if not 0.15 <= s["scan_interval"] <= 5:
            raise ValueError("OCR aralığı 0.15–5 saniye arasında olmalı; ilk deneme: 0.28.")
        if not 12 <= s["font_size"] <= 96 or not 1 <= s["overlay_bottom"] <= 40:
            raise ValueError("Yazı boyu 12–96, alttan mesafe %1–40 olmalı.")
        from PIL import Image
        crop_frame(Image.new("RGB", (200, 200)), s["crop_left"], s["crop_top"], s["crop_right"], s["crop_bottom"])
        if s["budget_try"] <= 0 or s["usd_try"] <= 0:
            raise ValueError("Bütçe limiti ve USD/TRY değeri pozitif olmalı.")
        return s

    def prepare(self, require_source=True, require_key=False):
        if self.closing:
            return None
        try:
            s = self._settings_from_ui()
            if require_source and not s["obs_source"]:
                raise ValueError("Önce OBS oyun kaynağını seç.")
            if require_key and not self.api_key.get().strip():
                raise ValueError("OpenAI API anahtarını gir.")
            secret_save("obs_password", self.obs_password.get())
            # Cloud settings/credential/ledger remain historical data. The local
            # path never writes an API credential, reserves money or calls SDKs.
            s['estimated_total_usd']=self.ledger.usd
            save_settings(s)
            self.settings = dict(s)
            # Runtime-only credentials; save_settings has a strict allowlist.
            s["obs_password_runtime"] = self.obs_password.get()
            s["api_key_runtime"] = self.api_key.get().strip()
            self.overlay_state.font = s["font_size"]
            self.overlay_state.bottom = s["overlay_bottom"]
            return s
        except Exception as exc:
            messagebox.showerror("Ayarları kontrol et", str(exc))
            return None

    def _obs(self, s: dict):
        return ObsSource(s["obs_password_runtime"], s["obs_port"], width=s.get("capture_width",960))

    def load_sources(self):
        s = self.prepare(require_source=False, require_key=False)
        if s is None:
            return
        self.status_var.set("OBS kaynakları okunuyor...")
        def go():
            try:
                obs = self._obs(s)
                try:
                    result = obs.list_inputs()
                finally:
                    obs.close()
                self.post("sources", result)
            except Exception as exc:
                self.post("error", "OBS bağlantısı başarısız: " + type(exc).__name__)
        self._spawn(go)

    def test_ocr(self):
        if getattr(self,'region_editor',None) is not None:
            self.region_editor.test_ocr();return
        if self.capture_lock.locked():
            self.open_region_editor()
            return
        self.open_region_editor()

    def demo(self):
        if getattr(self,'preview_active',False) or self.running:
            self.status_var.set('Tanılama sürerken örnek altyazı üretimi kapalı (OCR döngü koruması).')
            return
        s = self.prepare(require_source=False, require_key=False)
        if not s:
            return
        self._place_overlay(s)
        self.overlay_state.set("Burada ne olduğunu öğrenmeliyiz.", 12)
        self.log("Demo altyazısı 12 saniye boyunca PC/OBS üzerinde gösteriliyor. API harcaması yok.")

    def legacy_test_ai(self):
        if getattr(self,'running',False) or getattr(self,'preview_active',False) or self.diagnostic_active or self.diagnostic_mode.get():
            self.status_var.set('OCR tanılamasında OpenAI çağrıları kapalı.')
            return
        s = self.prepare(require_source=False, require_key=True)
        if s is None:
            return
        source = simpledialog.askstring("Çeviri kalitesini test et",
                   "Bir İngilizce oyun repliği gir:",
                   initialvalue="I've got your back. We should leave before the guards return.", parent=self.root)
        if not source or not source.strip():
            return
        try:
            self._place_overlay(s)
        except Exception as exc:
            messagebox.showerror("Ekran", str(exc))
            return
        session_id = self.session_id
        self.status_var.set("AI örnek çeviriyi hazırlıyor...")
        def go():
            engine = None
            try:
                memory = ContextMemory(s["game"], s["lore"])
                engine = TranslationEngine(s["api_key_runtime"], s["model"], memory, self.ledger)
                began = time.monotonic()
                translated, usage = engine.translate(source.strip())
                self.post_session(session_id, "ai_demo", translated, source.strip(), time.monotonic()-began, usage.usd)
                self.post("spent", )
            except Exception as exc:
                self.post_session(session_id, "error", "AI test: " + type(exc).__name__)
            finally:
                if engine is not None:
                    engine.client.close()
        self._spawn(go)

    def test_ai(self):
        if getattr(self,'running',False) or getattr(self,'preview_active',False) or self.diagnostic_active or self.diagnostic_mode.get():
            self.status_var.set('Yerel testi başlatmadan önce yakalamayı durdurun.');return
        s=self.prepare(require_source=False,require_key=False)
        if s is None:return
        try:model_manifest(s['local_model_path'],verify=False)
        except Exception as exc:messagebox.showerror('Yerel model',str(exc));return
        source=simpledialog.askstring('Yerel çeviri testi','İngilizce replik:',parent=self.root)
        if not source or not source.strip():return
        session_id=self.session_id
        def go():
            engine=None
            try:
                engine=WarmNMTClient(s['local_python'],s['local_model_path'],device=s['local_device'],
                    compute_type=s['local_compute_type'],workers=s['local_workers'],threads=s['local_threads'],
                    beam_size=s.get('local_beam_size',4))
                began=time.monotonic();r=engine.translate(source.strip())
                self.post_session(session_id,'ai_demo',r['text'],source.strip(),time.monotonic()-began,0)
            except Exception as exc:self.post_session(session_id,'error',str(exc))
            finally:
                if engine:engine.close()
        self._spawn(go)

    def _choose_local_model(self):
        selected=filedialog.askdirectory(title='ediz_nmt.json içeren yerel model klasörü')
        if selected:self.local_model_path.set(selected)

    def _place_overlay(self, s):
        if s["show_desktop"]:
            if not self.monitors_list:
                raise RuntimeError("Windows monitörü bulunamadı")
            self.overlay.show(self.monitors_list[s["monitor_index"]], s["font_size"], s["overlay_bottom"])
        else:
            self.overlay.hide()

    def start(self):
        if self.region_editor is not None:
            self.status_var.set('Başlatmadan önce OCR düzenleyicisini kaydet veya iptal et.');return
        if self.running or self.closing or any(w.is_alive() for w in self.workers):
            self.status_var.set("Önceki işlemlerin tamamlanması bekleniyor.")
            return
        diagnostic = bool(self.diagnostic_mode.get())
        s = self.prepare(require_key=False)
        if s is None:
            return
        if not self.server:
            messagebox.showerror("OBS overlay", "Yerel overlay sunucusu çalışmıyor. Programı yeniden başlat.")
            return
        if not diagnostic:
            try:
                model_manifest(s['local_model_path'],verify=False)
                if not Path(s['local_python']).is_file():raise ValueError('Yerel motor Python yolunu seçin.')
            except Exception as exc:messagebox.showerror('Yerel motor',str(exc));return
        try:
            self._place_overlay(s)
        except Exception as exc:
            messagebox.showerror("Monitör", str(exc))
            return
        detailed = bool(self.diagnostic_logs.get())
        if detailed and not diagnostic:
            messagebox.showwarning('Tanılama', "Ayrıntılı günlük için API'siz OCR tanılamasını seç.")
            return
        if detailed and not messagebox.askyesno('Hassas günlük',
                'Ham OCR metni ve süreler yerel JSONL dosyasına yazılacak. Özel metin içerebilir. Devam edilsin mi?'):
            return
        try:
            if self.subtitle_store is not None:
                self.subtitle_store.close()
                self.subtitle_store = None
                self.active_capture_settings=None
            self.subtitle_store = SubtitleStore(config_folder() / 'subtitles.sqlite3')
        except Exception as exc:
            messagebox.showerror('Yerel kayıt', 'SQLite açılamadı: ' + type(exc).__name__)
            return
        s = dict(s)
        s['_store'] = self.subtitle_store
        s['_capture_session'] = uuid.uuid4().hex
        s['_diagnostic'] = diagnostic
        s['_log_path'] = (config_folder() / 'diagnostics' / (s['_capture_session'] + '.jsonl')) if detailed else None
        self.diagnostic_active = diagnostic
        self.overlay_state.clear()
        self.running = True
        self.stop_evt = threading.Event()
        self.session_id += 1
        session_id = self.session_id
        jobs = None  # Translation backlog is durable SQLite, not a lossy RAM queue.
        self.overlay_state.bind(self.subtitle_store,s['_capture_session'],ready_first=True)
        self.shown_ids=set()
        self.metrics_saved_session=None
        memory = ContextMemory(s["game"], s["lore"])
        self.latest_seq = self.seq = 0
        self.timeline = SubtitleTimeline()
        self.start_at = time.monotonic()
        self.session_initial_usd = self.ledger.usd
        self.memory = memory
        self.start_btn.configure(text='■  DURDUR',state='normal')
        self.game_combo.configure(state='disabled')
        self.connection_var.set('OBS: Denetleniyor     Kamera: Açılıyor     AI: '+('Kapalı' if diagnostic else 'Bekliyor'))
        self.status_var.set("Başlatılıyor: OBS bağlantısı ve OCR hazırlanıyor...")
        self.log(f"Çeviri başlıyor: {s['game']} · yerel {s['translation_engine']} · kaynak: {s['obs_source']}")
        s['_ready']=threading.Event()
        self.active_capture_settings=s
        if not diagnostic:self._spawn(self.translate_worker, s, self.stop_evt, session_id, jobs, memory)
        self._spawn(self.capture_worker, s, self.stop_evt, session_id, jobs)

    def capture_worker(self, s, stop_flag, session_id, jobs):
        buffered = None
        ocr = None
        diagnostic = None
        runner = None
        if not self.capture_lock.acquire(blocking=False):
            self.post_session(session_id, 'error', 'Başka OCR testi çalışıyor.')
            self.post_session(session_id, 'stopped')
            return
        try:
            diagnostic = DiagnosticLog(s['_log_path'])
            ocr = SharedOCR(lambda:create_ocr(s.get('ocr_profile','bounded960_cpu2')))
            self.shared_ocr=ocr
            buffered = LatestFrames(lambda:self._make_capture_source(s),stop_flag,
                                    period=0,on_failure=lambda exc:self._capture_failed(stop_flag,session_id,exc))
            self.capture_feed=buffered
            self.preview_status='Yakalama işçisi durdu; son görüntü donduruldu.'
            store = s['_store']
            def change():
                self.seq += 1
                self.latest_seq = self.seq
                self.post_session(session_id, 'clear', self.seq)
            def accept(row, text, accepted_at):
                if stop_flag.is_set() or session_id!=self.session_id:
                    store.status(row,'cancelled');return
                self.post_session(session_id, 'source', text)
                if not s['_diagnostic']:
                    store.enqueue_translation(s['_capture_session'],row,text,'local:'+s['translation_engine'],accepted_at)
                else:
                    store.status(row, 'diagnostic_only')
            first=buffered.read()
            def frame():
                nonlocal first
                if first is not None:
                    packet,first=first,None
                    return packet
                return buffered.read()
            runner = CaptureRunner(frame,
                lambda image: crop_frame(image, s['crop_left'], s['crop_top'], s['crop_right'], s['crop_bottom']),
                ocr, store, s['_capture_session'], diagnostic, change, accept,
                s.get('fixed_ocr_interval',.04),
                ImageChangeGate(s.get('change_check_interval',.02),s.get('full_ocr_interval',.15))
                    if s.get('capture_schedule')=='adaptive' else None)
            # Do not create an API client until a safe raw camera frame exists.
            s['_ready'].set()
            self.post_session(session_id,'connections','OBS: Güvenli     Kamera: Bağlı     AI: '+('Kapalı · tanılama' if s['_diagnostic'] else 'Hazır · ilk istek bekleniyor'))
            self.post_session(session_id, 'status', 'OCR hazır · ' + ('API KAPALI' if s['_diagnostic'] else 'çeviri açık'))
            runner.run(stop_flag)
        except Exception as exc:
            if stop_flag.is_set():return
            cause=exc.__cause__ or exc
            detail=str(cause) if isinstance(cause,CaptureConfigurationError) else type(exc).__name__
            self.post_session(session_id, 'error', 'Canlı OCR / yerel kayıt: ' + detail)
            self.post_session(session_id, 'stopped')
        finally:
            # A plain summary contains no subtitle text and may outlive the session.
            try:
                if runner is not None:
                    self.post('capture_summary', runner.metrics.summary())
                if diagnostic is not None:
                    diagnostic.close()
            finally:
                try:
                    if buffered is not None:
                        buffered.close()
                finally:
                    if self.capture_feed is buffered:self.capture_feed=None
                    if self.shared_ocr is ocr:self.shared_ocr=None
                    self.capture_lock.release()

    def _capture_failed(self,stop_flag,session_id,exc):
        # Producer thread: invalidate immediately, before the UI event pump.
        stop_flag.set()
        if session_id==self.session_id:
            self.latest_seq+=1
            self.overlay_state.clear('source_lost')
            cause=exc.__cause__ or exc
            detail=str(cause) if isinstance(cause,CaptureConfigurationError) else 'OBS/kamera bağlantısı kesildi. OBS’yi ve Sanal Kamera’yı kontrol edin.'
            self.post_session(session_id,'error',detail)
            self.post_session(session_id,'stopped',detail)

    def legacy_translate_worker(self, s, stop_flag, session_id, jobs, memory):
        if s.get('_diagnostic'):return
        engine=None
        try:
            ready=s.get('_ready')
            if ready is not None:
                while not ready.wait(.05):
                    if stop_flag.is_set():return
            if stop_flag.is_set():return
            engine_started=time.monotonic()
            engine=TranslationEngine(s['api_key_runtime'],s['model'],memory,self.ledger)
            engine_init_ms=(time.monotonic()-engine_started)*1000
            store=s['_store']
            while not stop_flag.is_set():
                job=store.claim_translation(s['_capture_session'],time.monotonic())
                if job is None:
                    stop_flag.wait(.05);continue
                if stop_flag.is_set():break
                try:
                    if job['model']!=s['model']:raise ValueError('Oturum modeli değişti.')
                    began=time.monotonic()
                    text,usage=engine.translate(job['source'])
                    ended=time.monotonic()
                    store.complete_translation(job['id'],text,ended,usage)
                    timings=dict(getattr(engine,'last_timing',{}))
                    if engine_init_ms is not None:
                        timings['engine_init_ms']=engine_init_ms;engine_init_ms=None
                    store.record_timing(job['id'],timings)
                    if not stop_flag.is_set() and session_id==self.session_id:
                        memory.remember(s['model'],job['source'],text)
                        self.post_session(session_id,'translated',job['id'],text,job['source'],ended-began,usage.usd)
                    self.post('spent')
                except Exception as exc:
                    store.record_timing(job['id'],getattr(engine,'last_timing',{}))
                    store.fail_translation(job['id'],time.monotonic(),getattr(exc,'usage',None),getattr(exc,'cost_unknown',False))
                    self.post_session(session_id,'error','Çeviri alınamadı. Model erişimini, anahtarı ve bütçeyi kontrol edin. ('+type(exc).__name__+')')
                    if self.ledger.blocked or not self.ledger.can_spend():
                        stop_flag.set();self.overlay_state.clear('budget_or_unknown_cost')
                        self.post_session(session_id,'stopped','API bütçesi veya belirsiz maliyet nedeniyle durduruldu.');break
        except Exception as exc:
            self.post_session(session_id,'error','AI motoru başlatılamadı: '+type(exc).__name__)
            stop_flag.set();self.overlay_state.clear('ai_start_error')
            self.post_session(session_id,'stopped')
        finally:
            if '_store' in s and stop_flag.is_set():s['_store'].cancel_session(s['_capture_session'],'session_end')
            if engine is not None:engine.client.close()

    def translate_worker(self,s,stop_flag,session_id,jobs,memory):
        if s.get('_diagnostic'):return
        try:
            ready=s.get('_ready')
            if ready is not None:
                while not ready.wait(.02):
                    if stop_flag.is_set():return
            if stop_flag.is_set():return
            def result(job,text,elapsed,route):
                if session_id==self.session_id and not stop_flag.is_set():
                    self.post_session(session_id,'translated',job['id'],text,job['source'],elapsed,0)
            self.local_coordinator=LocalTranslationCoordinator(s,s['_store'],s['_capture_session'],stop_flag,
                result,lambda message:self.post_session(session_id,'error','Yerel motor: '+message),
                engine_factory=WarmNMTClient)
            self.local_coordinator.run()
            if stop_flag.is_set() and session_id==self.session_id:
                self.post_session(session_id,'stopped','Yerel çeviri motoru durdu; bulut fallback yapılmadı.')
        except Exception as exc:
            stop_flag.set();self.overlay_state.clear('local_engine_error')
            self.post_session(session_id,'error','Yerel motor başlatılamadı: '+str(exc))
            self.post_session(session_id,'stopped')
        finally:
            if '_store' in s and stop_flag.is_set():s['_store'].cancel_session(s['_capture_session'],'local_engine_end')

    def stop(self):
        self.session_id += 1
        self.stop_evt.set()
        active=getattr(self,'active_capture_settings',None)
        if active is not None:active['_store'].cancel_session(active['_capture_session'],'user_stop')
        self.running = False
        self.start_btn.configure(text='▶  ÇEVİRİYİ BAŞLAT',state='normal')
        self.game_combo.configure(state='readonly')
        self.connection_var.set('OBS: Bekliyor     Kamera: Durduruluyor     AI: Kapalı')
        self.status_var.set("Durduruldu. Yeni bir oturum başlatabilirsiniz.")
        self.overlay_state.clear()
        if hasattr(self,'last_translation_var'):self.last_translation_var.set('Türkçe çeviri burada görünecek.')
        self.overlay.hide()
        self._store_ledger()
        self.log("Çeviri durduruldu.")

    def _store_ledger(self):
        snapshot = self.ledger.snapshot()
        self.settings['estimated_total_usd'] = snapshot['usd']
        self.settings['token_total_in'] = snapshot['input_tokens']
        self.settings['token_total_out'] = snapshot['output_tokens']
        save_settings(self.settings)

    def _save_session_metrics(self):
        active=getattr(self,'active_capture_settings',None)
        if not active or self.subtitle_store is None:return
        session=active['_capture_session']
        if getattr(self,'metrics_saved_session',None)==session:return
        from core import atomic_json
        try:
            metrics=self.subtitle_store.session_metrics(session)
            if getattr(self,'local_coordinator',None):metrics['local_engine']=self.local_coordinator.summary()
            atomic_json(config_folder()/'last_session_metrics.json',metrics)
        except OSError:self.log('Oturum metrikleri diske yazılamadı; SQLite kayıtları korunuyor.')
        self.metrics_saved_session=session

    def export_srt(self):
        if not self.timeline.events:
            messagebox.showinfo("SRT", "Henüz kaydedilmiş Türkçe altyazı yok.")
            return
        filename = f"EdizGameTranslator_{datetime.now():%Y%m%d_%H%M}.srt"
        path = filedialog.asksaveasfilename(defaultextension=".srt", initialfile=filename,
                                            filetypes=[("SubRip subtitles", "*.srt")])
        if path:
            Path(path).write_text(self.timeline.srt(), encoding="utf-8-sig")
            self.log(f"SRT kaydedildi: {path}")

    def pump(self):
        if getattr(self,'pump_after',None) is not None:self.root.after_cancel(self.pump_after)
        self.pump_after=None
        if self.closing:return
        try:
            for _ in range(35):
                kind, args = self.events.get_nowait()
                if kind == 'session':
                    session_id, kind, args = args
                    if session_id != self.session_id or self.closing:
                        continue
                    if kind in ('translated', 'clear'):
                        seq, *args = args
                        if not self.running:
                            continue
                if kind == 'clear':
                    pass  # OCR disappearance/change must not cancel a Turkish read clock.
                elif kind == "log":
                    self.log(args[0])
                elif kind == "sources":
                    self.source_combo["values"] = args[0]
                    if not self.source.get() and args[0]:
                        self.source.set(args[0][0])
                    self.log(f"OBS kaynakları: {', '.join(args[0]) or '(yok)'}")
                    self.status_var.set(f"{len(args[0])} kaynak bulundu.")
                elif kind == "source":
                    # Raw OCR is opt-in in diagnostic files, not in the default UI log.
                    self.status_var.set('Replik yerel kayda alındı · API KAPALI' if self.diagnostic_active
                                        else 'Replik kaydedildi · AI çevirisi yapılıyor...')
                    self.last_source_var.set(args[0])
                elif kind == 'connections':
                    self.connection_var.set(args[0])
                elif kind == 'capture_summary':
                    summary = args[0]
                    ocr = summary['stages'].get('ocr_ms', {})
                    self.log(f"OCR özeti: {summary['frames']} kare, {summary['accepted']} kabul; "
                             f"OCR p50/p95 {ocr.get('p50', 0):.1f}/{ocr.get('p95', 0):.1f} ms; "
                             f"CPU (tek çekirdek ölçeği) %{summary['cpu_one_core_percent']:.1f}")
                elif kind == "ai_demo":
                    translated, source, elapsed, cost = args
                    self.overlay_state.set(translated, 12)
                    self.log(f"AI TEST EN: {source}")
                    self.log(f"AI TEST TR ({elapsed:.2f} sn, ${cost:.5f}): {translated}")
                    self.status_var.set(f"AI test tamamlandı · {elapsed:.2f} saniye")
                elif kind == "translated":
                    translated, source, elapsed, cost,*_ = args
                    if hasattr(self,'last_translation_var'):
                        self.last_translation_var.set(translated)
                        self.connection_var.set('OBS: Güvenli     Kamera: Bağlı     AI: Yanıt alındı')
                    self.log(f"TR ({elapsed:.2f} sn, ${cost:.5f}): {translated}")
                    self.status_var.set(f"Aktif · son AI yanıtı {elapsed:.2f} saniye")
                elif kind == "status":
                    self.status_var.set(args[0])
                elif kind == "error":
                    self.log("HATA: " + args[0])
                    self.status_var.set("Hata · ayrıntılar günlükte")
                elif kind == "stopped":
                    self.stop()
                    if args:self.status_var.set('Güvenlik için durduruldu. '+args[0])
                elif kind == "spent":
                    self._store_ledger()
        except queue.Empty:
            pass
        prefix = "Geçmiş maliyet mutabakatı bekliyor. " if self.ledger.blocked else ""
        self.cost_var.set(prefix + f"Geçmiş bulut harcaması ≈ {self.ledger.spent_try():.2f} TL."
                          " Yerel çeviri bu bütçeyi kullanmaz.")
        if hasattr(self,'session_cost_var'):
            self.session_cost_var.set("Yerel çeviri · ücretli API kapalı")
            if not self.running and not self.preview_active and not any(w.is_alive() for w in self.workers):
                self.connection_var.set('OBS: Bekliyor     Kamera: Kapalı     AI: Kapalı')
                self._save_session_metrics()
        state=self.overlay_state.snapshot()
        blocks=state['blocks']
        self.overlay.render_blocks(blocks)
        if self.overlay.enabled:
            self.overlay_state.ack([b['id'] for b in blocks if b['started'] is None],state['generation'],'tk_render_submitted')
        if hasattr(self,'shown_ids'):
            for b in blocks:
                if b['started'] is not None and b['id'] not in self.shown_ids:
                    self.timeline.add(max(0,b['started']-self.start_at),b['text'])
            self.shown_ids={b['id'] for b in blocks if b['started'] is not None}
        if hasattr(self,'session_cost_var') and self.running:
            suffix=f" · Bekleyen: {state['waiting']} + AI {state['translation_pending']} · okuma birikimi ≈ {state['backlog_seconds']:.1f} sn"
            self.session_cost_var.set(self.session_cost_var.get()+suffix+(' · YOĞUNLUK YÜKSEK' if state['overloaded'] else ''))
        if not self.closing:self.pump_after = self.root.after(20, self.pump)

    def close(self):
        if self.closing:
            return
        self.closing = True
        if getattr(self,'page_after',None) is not None:
            self.root.after_cancel(self.page_after);self.page_after=None
        if getattr(self,'pump_after',None) is not None:
            self.root.after_cancel(self.pump_after);self.pump_after=None
        if getattr(self,'region_editor',None) is not None:self.region_editor.close()
        if getattr(self,'preview_stop',None) is not None:self.preview_stop.set()
        self.stop()
        self._finish_close()

    def _finish_close(self):
        if getattr(self,'close_after',None) is not None:
            self.root.after_cancel(self.close_after);self.close_after=None
        if any(worker.is_alive() for worker in self.workers):
            self.status_var.set('Kapanıyor: işlemler ve harcama kaydı bekleniyor...')
            self.close_after=self.root.after(100, self._finish_close)
            return
        for worker in self.workers:
            worker.join()
        self._store_ledger()
        if self.subtitle_store is not None:
            self._save_session_metrics()
            self.subtitle_store.close()
            self.subtitle_store = None
            self.active_capture_settings=None
        self.overlay_state.clear()
        self.overlay_state.close()
        self.overlay.destroy()
        if getattr(self, 'pump_after', None) is not None:
            self.root.after_cancel(self.pump_after)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.root.destroy()


def main():
    if sys.platform != "win32":
        print("Bu ilk masaüstü sürümü Windows 10/11 içindir.")
        sys.exit(1)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    from instance_lock import InstanceLock
    try:
        lock = InstanceLock(config_folder() / 'instance.lock')
    except OSError:
        messagebox.showerror('Ediz Game Translator', 'Başka bir uygulama örneği açık.')
        return
    try:
        root = tk.Tk()
        MainWindow(root)
        root.mainloop()
    finally:
        lock.close()


if __name__ == "__main__":
    main()
