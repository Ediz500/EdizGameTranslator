"""Ediz Game Translator: local settings, OCR filtering and subtitle timeline."""
from __future__ import annotations

import json
import math
import os
import uuid
import re
from pathlib import Path
from typing import Any
from copy import deepcopy
from ediz_game_translator.storage.region_profiles import normalize_profiles


DEFAULTS: dict[str, Any] = {
    "obs_port": 4455,
    "obs_source": "",
    "capture_width": 960,
    "capture_method": 'ediz_game_translator.capture.virtual_camera',
    "ocr_profile": "bounded960_cpu2",
    "camera_config": "",
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
    "game": "Genel oyun",
    "lore": "",
    "show_desktop": True,
    "transcript_srt": True,
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
        # Unknown historical fields are ignored. No credential or legacy data files are touched.
        settings['capture_method']='ediz_game_translator.capture.virtual_camera'
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
