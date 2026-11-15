"""Local, sequential capture pipeline. No AI SDK dependency or network API calls."""
from dataclasses import dataclass
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import statistics
import time

from core import clean_ocr, subtitle_observation
from dialogue_filter import dialogue_candidates
from subtitle_tracking import ActiveSubtitles
from frame_sources import FramePacket


def same_line(a, b):
    """Preserve words, negation, numbers and punctuation; only known glyph noise.

    No general edit-distance merge: 'east'/'west', 'can'/'can't' are different.
    Digit confusion is tolerated only inside long alphabetic words, never numbers.
    """
    def normalize(text):
        words = clean_ocr(text).casefold().replace("’", "'").split()
        words = [word.rstrip(".,;") for word in words]
        return [re.sub(r'(?<=[a-z])0(?=[a-z])', 'o', word)
                if len(word) >= 5 and sum(c.isalpha() for c in word) >= 4
                and all(c.isalpha() or c in "0.,!?'’" for c in word) else word
                for word in words]
    return normalize(a) == normalize(b)


@dataclass
class Decision:
    text: str
    reason: str
    changed: bool
    accepted: bool
    first_seen: float


class SubtitleGate:
    def __init__(self):
        self.text = ''
        self.best = ''
        self.best_score = 0
        self.first_seen = 0
        self.count = 0
        self.accepted = False

    def observe(self, text, confidence, now):
        text = clean_ocr(text)
        changed = not same_line(self.text, text)
        if changed:
            self.text = self.best = text
            self.best_score = confidence
            self.first_seen = now
            self.count = 0
            self.accepted = False
        if not text:
            return Decision('', 'empty', changed, False, now)
        if not math.isfinite(confidence) or confidence < .65:
            self.count = 0
            return Decision(text, 'below_confidence', changed, False, self.first_seen)
        self.count += 1
        if confidence > self.best_score:
            self.best, self.best_score = text, confidence
        if self.accepted:
            return Decision(self.best, 'duplicate', changed, False, self.first_seen)
        reliable = confidence >= .94 and sum(c.isalpha() for c in text) >= 3
        if reliable or self.count >= 2:
            self.accepted = True
            return Decision(self.best, 'high_confidence' if reliable else 'confirmed',
                            changed, True, self.first_seen)
        return Decision(text, 'pending_confirmation', changed, False, self.first_seen)


class DiagnosticLog:
    """Opt-in JSONL only. Caller provides fields, never a settings/credential dict."""
    def __init__(self, path=None):
        self.stream = None
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.stream = Path(path).open('x', encoding='utf-8')

    def write(self, kind, **fields):
        if self.stream:
            self.stream.write(json.dumps(dict(kind=kind, **fields), ensure_ascii=False,
                                         default=float) + '\n')
            self.stream.flush()

    def close(self):
        if self.stream:
            self.stream.close()


class Metrics:
    def __init__(self):
        self.samples = {name: [] for name in ('screenshot_ms', 'crop_ms', 'ocr_ms',
                                             'decision_ms', 'storage_ms', 'dispatch_ms', 'cycle_ms',
                                             'frame_age_ms', 'result_age_ms', 'frame_wait_ms', 'frame_interval_ms')}
        self.count = self.accepted = self.overruns = self.skipped = 0
        self.reasons=Counter()
        self.filter_reasons=Counter()
        self.raw_lines=0
        self.wall = time.perf_counter()
        self.cpu = time.process_time()

    def summary(self):
        wall = max(.000001, time.perf_counter() - self.wall)
        cpu = time.process_time() - self.cpu
        stages = {}
        for name, values in self.samples.items():
            if values:
                ordered = sorted(values)
                stages[name] = dict(p50=statistics.median(values),
                                    p95=ordered[max(0, math.ceil(len(values)*.95)-1)])
        return dict(frames=self.count, accepted=self.accepted, overruns=self.overruns,
                    reason_counts=dict(self.reasons),filter_rejections=dict(self.filter_reasons),raw_lines=self.raw_lines,
                    processed_fps=self.count/wall,
                    wall_seconds=wall, process_cpu_seconds=cpu, skipped_frames=self.skipped,
                    cpu_one_core_percent=100*cpu/wall,
                    cpu_machine_percent=100*cpu/wall/(os.cpu_count() or 1), stages=stages)


class CaptureRunner:
    def __init__(self, frame, crop, ocr, store, session, diagnostic, on_change,
                 on_accept, interval=.28):
        if not math.isfinite(interval) or not .15 <= interval <= 5:
            raise ValueError('OCR interval must be 0.15–5 seconds')
        self.frame, self.crop, self.ocr = frame, crop, ocr
        self.store, self.session, self.diagnostic = store, session, diagnostic
        self.on_change, self.on_accept = on_change, on_accept
        self.interval = interval
        self.gate = SubtitleGate()  # Legacy rule retained for comparison tests.
        self.tracker = ActiveSubtitles()
        self.foreground = None
        self.visible_keys = ()
        self.metrics = Metrics()
        self.active_id = None
        self.active_first = self.active_last = None
        self.previous_start=None

    def step(self, stop=None):
        # One synchronous screenshot and OCR at a time; no catch-up request burst.
        start = time.perf_counter()
        request_utc = time.time()
        image = self.frame()
        received = time.perf_counter()
        captured_utc = time.time()
        packet = image if isinstance(image,FramePacket) else None
        acquisition_ms = (received-start)*1000
        if packet:
            image = packet.image
            captured_utc = packet.captured_utc
            acquisition_ms = packet.read_ms
        sample_time = packet.captured_mono if packet else received
        region = self.crop(image)
        ocr_start = time.perf_counter()
        result = self.ocr(region)
        ocr_end = time.perf_counter()
        if stop is not None and stop.is_set():
            self.diagnostic.write('cancelled', session=self.session, ocr_start=ocr_start, ocr_end=ocr_end)
            return 0
        candidates, evidence = dialogue_candidates(result, region.width, getattr(region,'height',0))
        actions = self.tracker.update(candidates,sample_time)
        primary = max(actions,key=lambda a:a.candidate.box[3] if a.candidate.box else a.candidate.indices[-1] if a.candidate.indices else 0) if actions else None
        text = primary.candidate.text if primary else ''
        confidence = primary.candidate.confidence if primary else 0
        reason = primary.reason if primary else 'empty'
        key = primary.track.key if primary else None
        visible_keys=tuple(sorted(a.track.key for a in actions))
        changed = (key != self.foreground or visible_keys != self.visible_keys
                   or any(a.reason in ('continuation','extension') for a in actions))
        decision = Decision(text,reason,changed,any(a.new for a in actions),
                            primary.track.first_seen if primary else sample_time)
        self.metrics.reasons[reason]+=1
        self.metrics.filter_reasons.update(r['reason'] for r in evidence['rejected'])
        raw_texts = list(getattr(result,'txts',None) or [])
        raw_scores = [float(x) for x in (getattr(result,'scores',None) or [])]
        raw_boxes = getattr(result,'boxes',None)
        if hasattr(raw_boxes,'tolist'): raw_boxes=raw_boxes.tolist()
        self.metrics.raw_lines+=len(raw_texts)
        decided = time.perf_counter()
        if changed:
            self.on_change()  # Invalidate before any potentially blocking disk operation.
        # Raw frame is durable BEFORE any canonical correction or dispatch.
        frame_id = self.store.frame(self.session,sample_time,captured_utc,raw_texts,raw_scores,raw_boxes)
        for expired in self.tracker.expired:
            if expired.row is not None:
                self.store.finish(expired.row,expired.last_seen,captured_utc-(sample_time-expired.last_seen))
        if changed:
            if self.active_id is not None:
                self.store.finish(self.active_id,sample_time,captured_utc)
                self.diagnostic.write('subtitle_end',subtitle_id=self.active_id,
                    observed_duration_ms=(sample_time-self.active_first)*1000,
                    end_mono=sample_time,end_reason='blank' if not text else 'changed')
        self.foreground=key
        self.visible_keys=visible_keys
        for action in actions:
            track,candidate=action.track,action.candidate
            if action.new:
                track.row=self.store.accept(self.session,candidate.text,track.first_seen,sample_time,
                    captured_utc,decided,candidate.confidence,action.reason,
                    speaker=track.speaker,track_key=track.key)
                self.metrics.accepted+=1
                if track.canonical != candidate.text:
                    self.store.revise(track.row,track.canonical,sample_time,'best_observation')
            elif action.corrected and track.row is not None:
                self.store.revise(track.row,track.canonical,sample_time,action.reason)
                if not action.dispatch:
                    self.store.refresh_pending_source(self.session,track.row,track.canonical)
            if track.row is not None:
                self.store.seen(track.row,sample_time,captured_utc)
            self.store.observation(frame_id,track.row,track.key,candidate.speaker,candidate.text,
                                   candidate.confidence,candidate.box,action.reason)
        self.active_id=primary.track.row if primary else None
        if primary:
            self.active_first=primary.track.first_seen
            self.active_last=sample_time
        stored = time.perf_counter()
        for action in actions:
            if action.dispatch:
                # Each callback is ONE speaker's current observed fragment, never a mixed string.
                self.on_accept(action.track.row,action.track.canonical,decided)
        end = time.perf_counter()
        values = (acquisition_ms, (ocr_start-received)*1000,
                  (ocr_end-ocr_start)*1000, (decided-ocr_end)*1000,
                  (stored-decided)*1000, (end-stored)*1000, (end-start)*1000,
                  max(0,(ocr_start-sample_time)*1000), max(0,(ocr_end-sample_time)*1000), (received-start)*1000,
                  (start-self.previous_start)*1000 if self.previous_start is not None else 0)
        self.previous_start=start
        for name, value in zip(self.metrics.samples, values):
            self.metrics.samples[name].append(value)
            # Bound memory for long sessions. Summary covers latest 4096 frames.
            if len(self.metrics.samples[name]) > 4096:
                del self.metrics.samples[name][0]
        self.metrics.count += 1
        self.metrics.skipped += packet.skipped if packet else 0
        self.metrics.overruns += end-start > self.interval
        self.diagnostic.write('frame', session=self.session, request_utc=request_utc,
            request_mono=start, received_mono=received, received_utc=captured_utc,
            ocr_start=ocr_start, ocr_end=ocr_end,
            raw_texts=raw_texts,
            raw_boxes=raw_boxes,
            candidates=[dict(text=a.candidate.text,speaker=a.candidate.speaker,track=a.track.key,
                             subtitle_id=a.track.row,action=a.reason,new_canonical=a.new,dispatch=a.dispatch) for a in actions],
            filter_evidence=evidence, frame_sequence=packet.sequence if packet else self.metrics.count,
            skipped_frames=packet.skipped if packet else 0, image_width=image.width if hasattr(image,'width') else None,
            raw_scores=raw_scores,
            text=text, confidence=confidence, reason=decision.reason,
            selection_reason='selected' if text else ('filtered_out' if getattr(result, 'txts', None) else 'no_ocr_text'),
            accepted=decision.accepted, first_seen=decision.first_seen,
            observed_duration_ms=(sample_time-decision.first_seen)*1000,
            subtitle_id=self.active_id, **dict(zip(self.metrics.samples, values)))
        return max(0, self.interval - (time.perf_counter()-start))

    def run(self, stop):
        try:
            while not stop.is_set():
                stop.wait(self.step(stop))
        finally:
            for track in self.tracker.tracks:
                if track.row is not None:
                    self.store.finish(track.row,None,None)
            if self.active_id is not None:
                # Last seen is a lower bound, not an invented true subtitle end.
                self.diagnostic.write('subtitle_end', subtitle_id=self.active_id,
                    observed_duration_ms=(self.active_last-self.active_first)*1000,
                    end_mono=None, end_reason='stopped_lower_bound')
            self.diagnostic.write('summary', session=self.session, **self.metrics.summary())
