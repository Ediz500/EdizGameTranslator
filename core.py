"""Ediz Game Translator: platform-independent translation, filtering and budget logic."""
from __future__ import annotations

import json
import math
import os
import uuid
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from copy import deepcopy
from region_profiles import normalize_profiles
from model_config import MODELS,DEFAULT_MODEL,model_spec

PRICE_PER_MILLION = {name:(s.input,s.output) for name,s in MODELS.items()}

DEFAULTS: dict[str, Any] = {
    "obs_port": 4455,
    "obs_source": "",
    "capture_width": 960,
    "capture_method": "virtual_camera",
    "ocr_profile": "bounded960_cpu2",
    "camera_config": "",
    "model": DEFAULT_MODEL,
    "translation_engine": "ct2-marian",
    "local_python": "",
    "local_model_path": "",
    "local_device": "cpu",
    "local_compute_type": "int8",
    "local_workers": 2,
    "local_threads": 2,
    "local_beam_size": 4,
    "translation_pack": "",
    "capture_schedule": "fixed_fast",
    "fixed_ocr_interval": 0.04,
    "change_check_interval": 0.02,
    "full_ocr_interval": 0.15,
    "display_transport": "sse",
    "crop_left": 0,
    "crop_top": 65,
    "crop_right": 100,
    "crop_bottom": 94,
    "ocr_regions": {},
    "scan_interval": 0.28,
    "translation_max_age": 5.0,  # Legacy setting retained; no longer hides live dialogue.
    "monitor_index": 0,
    "font_size": 36,
    "overlay_bottom": 10,
    "budget_try": 5000.0,
    "usd_try": 50.0,
    "game": "Genel oyun",
    "lore": "",
    "show_desktop": True,
    "transcript_srt": True,
    "estimated_total_usd": 0.0,
    "token_total_in": 0,
    "token_total_out": 0,
}


def config_folder() -> Path:
    import os
    if os.environ.get('EDIZ_CONFIG_DIR'):
        return Path(os.environ['EDIZ_CONFIG_DIR']).expanduser().resolve()
    root = Path(os.environ.get("APPDATA") or Path.home())
    return root / "EdizGameTranslator"


def load_settings() -> dict:
    p = config_folder() / "settings.json"
    try:
        incoming = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(incoming, dict):
            return deepcopy(DEFAULTS)
        settings=deepcopy(DEFAULTS) | {k: v for k, v in incoming.items() if k in DEFAULTS}
        try:settings['ocr_regions']=normalize_profiles(settings.get('ocr_regions',{}))
        except ValueError:settings['ocr_regions']={}
        # No destructive migration; legacy crop, notes, keys and ledgers stay intact.
        settings['capture_method']='virtual_camera'
        return settings
    except (ValueError, OSError):
        return deepcopy(DEFAULTS)


def save_settings(settings: dict) -> None:
    p = config_folder() / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    allowed = {k: settings[k] for k in DEFAULTS if k in settings}
    if 'ocr_regions' in allowed:allowed['ocr_regions']=normalize_profiles(allowed['ocr_regions'])
    atomic_json(p, allowed)


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def clean_ocr(text: str) -> str:
    text = re.sub(r"[\r\t\n]+", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    # Occasional OCR decorative characters, no removal of punctuation important to translation.
    text = text.strip(" |\\_•·")
    return text[:360]


def key_for(text: str) -> str:
    return re.sub(r"\W+", "", clean_ocr(text).casefold(), flags=re.UNICODE)


def subtitle_observation(result: Any, image_width: int) -> tuple[str, float]:
    """Prefer centered, horizontally written lines in the selected crop region."""
    texts = list(getattr(result, "txts", None) or [])
    scores = list(getattr(result, "scores", None) or [])
    boxes = getattr(result, "boxes", None)
    lines = []
    for i, raw in enumerate(texts):
        txt = clean_ocr(str(raw))
        if len(txt) < 3 or not any(c.isalpha() for c in txt):
            continue
        score = float(scores[i]) if i < len(scores) else 0.7
        if not math.isfinite(score) or score < 0.46 or score > 1:
            continue
        cx = image_width / 2
        cy = i * 20
        if boxes is not None and i < len(boxes):
            box = boxes[i]
            try:
                cx = sum(float(p[0]) for p in box) / len(box)
                cy = sum(float(p[1]) for p in box) / len(box)
            except Exception:
                pass
        if image_width and not (.12 * image_width <= cx <= .88 * image_width):
            continue
        # Don't let controller hints such as 'Press X' dominate a subtitle.
        if re.fullmatch(r"(?i)(press|hold|skip|back|continue|cancel|confirm)\s+[a-z0-9]{1,4}", txt):
            continue
        lines.append((cy, cx, txt, score))
    # A crop may contain quest instructions; prefer the three lowest lines.
    lines.sort(key=lambda r: r[0])
    selected = lines[-3:]
    return (clean_ocr(" ".join(x[2] for x in selected)),
            min((x[3] for x in selected), default=0.0))


def choose_subtitle(result: Any, image_width: int) -> str:
    return subtitle_observation(result, image_width)[0]


@dataclass(frozen=True)
class TranslationUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    api_called: bool = True


class BudgetLedger:
    """Single-instance durable reservations; uncertain billing blocks more calls."""
    def __init__(self, initial_usd, usd_try, budget_try, path=None, initial_in=0, initial_out=0):
        self._lock = threading.RLock()
        self.path = Path(path) if path else None
        self.usd = self._number(initial_usd)
        self.rate = self._number(usd_try, True)
        self.cap_try = self._number(budget_try)
        self.total_in = int(self._number(initial_in))
        self.total_out = int(self._number(initial_out))
        self.pending = {}
        self.blocked = False
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                self.usd = self._number(data['usd'])
                self.total_in = int(self._number(data['input_tokens']))
                self.total_out = int(self._number(data['output_tokens']))
                self.blocked = bool(data['blocked'] or data['pending'])
            except (ValueError, KeyError, TypeError, OSError):
                raise RuntimeError('Harcama kaydi okunamadi; API guvenlik icin kapali.') from None

    @staticmethod
    def _number(value, positive=False):
        value = float(value)
        if not math.isfinite(value) or value < 0 or (positive and value == 0):
            raise ValueError('Butce ve kur sonlu, negatif olmayan degerler olmali; kur sifir olamaz.')
        return value

    def configure(self, rate, cap):
        rate, cap = self._number(rate, True), self._number(cap)
        with self._lock:
            self.rate, self.cap_try = rate, cap

    def _persist(self):
        if self.path:
            atomic_json(self.path, self.snapshot())

    def snapshot(self):
        with self._lock:
            return dict(usd=self.usd, input_tokens=self.total_in, output_tokens=self.total_out,
                        blocked=self.blocked, pending=dict(self.pending))

    def can_spend(self):
        with self._lock:
            return not self.blocked and self.cap_try > 0 and (self.usd + .05) * self.rate <= self.cap_try

    def reserve(self, amount):
        amount = self._number(amount, True)
        with self._lock:
            if self.blocked or self.cap_try <= 0 or (self.usd + amount) * self.rate > self.cap_try:
                raise RuntimeError('Tahmini limit veya belirsiz maliyet nedeniyle API kapali.')
            token = uuid.uuid4().hex
            self.usd += amount
            self.pending[token] = amount
            try:
                self._persist()
            except Exception:
                self.blocked = True
                raise RuntimeError('Harcama rezervi kaydedilemedi; API cagrisi yapilmadi.') from None
            return token

    def uncertain(self, token):
        with self._lock:
            self.blocked = True
            self._persist()

    def settle(self, token, model, input_tokens, output_tokens,cached_tokens=0,cache_write_tokens=0):
        with self._lock:
            reserved = self.pending.pop(token)
            cost = self._cost(model, input_tokens, output_tokens,cached_tokens,cache_write_tokens)
            self.usd = max(0, self.usd - reserved + cost)
            self.total_in += input_tokens
            self.total_out += output_tokens
            if cost > reserved:
                self.blocked = True
            try:
                self._persist()
            except Exception:
                self.blocked = True
                raise RuntimeError('Harcama kaydi yazilamadi; API guvenlik icin kapali.') from None
            return TranslationUsage(input_tokens, output_tokens, cost)

    @staticmethod
    def _cost(model, input_tokens, output_tokens,cached_tokens=0,cache_write_tokens=0):
        spec=model_spec(model)
        return ((max(0,input_tokens-cached_tokens-cache_write_tokens)*spec.input +
                 cached_tokens*spec.cached+cache_write_tokens*spec.write)+max(0,output_tokens)*spec.output)/1_000_000

    def record(self, model, input_tokens, output_tokens):
        # Offline accounting compatibility; network requests use reserve/settle.
        with self._lock:
            cost = self._cost(model, input_tokens, output_tokens)
            self.usd += cost
            self.total_in += max(0, input_tokens)
            self.total_out += max(0, output_tokens)
            self._persist()
            return TranslationUsage(input_tokens, output_tokens, cost)

    def spent_try(self):
        with self._lock:
            return self.usd * self.rate


class ContextMemory:
    def __init__(self, game: str, lore: str):
        self.game = game.strip()[:100] or "Bilinmeyen oyun"
        self.lore = lore.strip()[:1600]
        self.history: deque[tuple[str, str]] = deque(maxlen=8)
        self.cache: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def prompt(self, source: str) -> str:
        with self._lock:
            recent = "\n".join(f"EN: {a}\nTR: {b}" for a, b in list(self.history)[-6:]) or "(Yok)"
        return (
            f"OYUN: {self.game}\n"
            f"KARAKTERLER / TERİMLER / HİKÂYE BAĞLAMI (kullanıcı notu): {self.lore or '(Yok)'}\n"
            f"SON ÇEVRİLMİŞ REPLİKLER:\n{recent}\n"
            f"YENİ İNGİLİZCE ALTYAZI:\n{source}\n"
            "SADECE TÜRKÇE ÇEVİRİ:"
        )

    def cached(self, model: str, source: str) -> str | None:
        with self._lock:
            return self.cache.get((model, clean_ocr(source).casefold()))

    def remember(self, model: str, source: str, translated: str) -> None:
        with self._lock:
            self.cache[(model, clean_ocr(source).casefold())] = translated
            if len(self.cache) > 1000:
                self.cache.clear()
            self.history.append((source, translated))


TRANSLATION_INSTRUCTIONS = """You are an expert Turkish localizer for a live story-driven video game stream.
Translate English game subtitles into natural, professional Turkish while preserving precisely what is said.
Use the provided game context, prior dialogue, character names and terminology where relevant.
Preserve speaker identity, proper nouns, relationships, intent, humor, emotional tone, swear words and continuity.
Do not hallucinate facts or add lore, context or spoilers; do not paraphrase away important plot facts.
Translate the current line only; previous dialogue is context, not text to translate.
If source is incomplete, keep the ambiguity rather than inventing missing content.
Output ONLY the Turkish subtitle text, no quotes, markdown, explanations or labels.
Keep subtitle compact and readable, maximum two short sentences when possible."""


class TranslationResultError(RuntimeError):
    def __init__(self,message,usage=None,cost_unknown=False):
        super().__init__(message)
        self.usage=usage;self.cost_unknown=cost_unknown


class TranslationEngine:
    def __init__(self, api_key: str, model: str, memory: ContextMemory, ledger: BudgetLedger):
        self.spec=model_spec(model)
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, timeout=14.0, max_retries=0)
        self.model = model
        self.memory = memory
        self.ledger = ledger
        self.last_timing = {}

    def translate(self, source: str) -> tuple[str, TranslationUsage]:
        started=time.monotonic()
        self.last_timing={}
        cached = self.memory.cached(self.model, source)
        if cached:
            self.last_timing={'cache_hit':True,'total_ms':(time.monotonic()-started)*1000}
            return cached, TranslationUsage(api_called=False)
        if not source.strip() or len(source) > 360:
            raise ValueError('Altyazi 1-360 karakter olmali.')
        prompt = self.memory.prompt(source)
        # Pessimistic byte estimate plus protocol framing; still local estimation.
        input_bound = len((TRANSLATION_INSTRUCTIONS + prompt).encode('utf-8')) + 1024
        price_in, price_out = self.spec.write, self.spec.output
        reserve = max(.05, (input_bound * price_in + 250 * price_out) / 1_000_000)
        token = self.ledger.reserve(reserve)
        requested=time.monotonic()
        self.last_timing={'cache_hit':False,'prepare_ms':(requested-started)*1000}
        try:
            try:
                response = self.client.responses.create(
                    model=self.model, instructions=TRANSLATION_INSTRUCTIONS,
                    input=prompt, reasoning={"effort": self.spec.effort}, max_output_tokens=250, store=False,
                    service_tier='default')
            finally:
                returned=time.monotonic()
                self.last_timing['request_call_ms']=(returned-requested)*1000
            usage = getattr(response, 'usage', None)
            counts = (getattr(usage, 'input_tokens', None), getattr(usage, 'output_tokens', None))
            if any(type(n) is not int or n < 0 for n in counts):
                raise RuntimeError('Unknown usage')
            detail=getattr(usage,'input_tokens_details',None)
            cached=getattr(detail,'cached_tokens',0) or 0
            writes=getattr(detail,'cache_write_tokens',0) or 0
            if any(type(n) is not int or n<0 for n in (cached,writes)) or cached+writes>counts[0]:
                raise RuntimeError('Unknown cache usage')
        except Exception:
            self.ledger.uncertain(token)
            raise TranslationResultError('API sonucu/maliyeti belirsiz; yeni istekler durduruldu. Harcama kaydini kontrol et.',cost_unknown=True) from None
        detail = self.ledger.settle(token, self.model, *counts,cached_tokens=cached,cache_write_tokens=writes)
        if getattr(response,'status','completed')!='completed':
            raise TranslationResultError('AI yanıtı tamamlanmadı. Kullanım kaydedildi; eksik çeviri gösterilmedi.',detail)
        text = (response.output_text or "").strip().strip('"“”')
        if not text:
            raise TranslationResultError("AI boş çeviri döndürdü; model yanıtı kontrol edilmeli.",detail)
        self.last_timing.update(result_ms=(time.monotonic()-returned)*1000,
                                total_ms=(time.monotonic()-started)*1000)
        return text, detail


class SubtitleTimeline:
    def __init__(self):
        self.events: list[tuple[float, float, str]] = []
        self.last_start: float | None = None
        self.session_start: float | None = None

    def add(self, time_seconds: float, text: str) -> None:
        if self.events:
            start, _, last_text = self.events[-1]
            self.events[-1] = (start, max(start + .3, time_seconds), last_text)
        self.events.append((time_seconds, time_seconds + 5.0, text))

    @staticmethod
    def _srt_time(sec: float) -> str:
        ms = max(0, round(sec * 1000))
        hh, rem = divmod(ms, 3_600_000)
        mm, rem = divmod(rem, 60_000)
        ss, milli = divmod(rem, 1_000)
        return f"{hh:02}:{mm:02}:{ss:02},{milli:03}"

    def srt(self) -> str:
        chunks = []
        for i, (start, end, text) in enumerate(self.events, 1):
            chunks.append(f"{i}\n{self._srt_time(start)} --> {self._srt_time(end)}\n{text}\n")
        return "\n".join(chunks)
