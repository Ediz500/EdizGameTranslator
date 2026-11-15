"""Bounded latest-frame handoff; only one producer touches its capture device."""
from dataclasses import dataclass
import threading
import time


@dataclass
class FramePacket:
    image: object
    sequence: int
    captured_mono: float
    captured_utc: float
    read_ms: float
    skipped: int = 0
    source_metrics: dict | None = None


class LatestFrames:
    def __init__(self, factory, stop, period=.1,on_failure=None):
        self.factory, self.stop, self.period = factory, stop, period
        self.condition = threading.Condition()
        self.latest = None
        self.error = None
        self.consumed = 0
        self.local_stop = threading.Event()
        self.on_failure=on_failure
        self.thread = threading.Thread(target=self._produce, name='capture-device', daemon=False)
        self.thread.start()

    def _produce(self):
        source = None
        try:
            source = self.factory()
            seq=0
            while not self.stop.is_set() and not self.local_stop.is_set():
                began=time.perf_counter()
                image=source.read()
                now=time.perf_counter(); seq+=1
                packet=FramePacket(image,seq,now,time.time(),(now-began)*1000,
                                   source_metrics=getattr(source,'last_timing',None))
                with self.condition:
                    self.latest=packet
                    self.condition.notify_all()
                self.local_stop.wait(max(0,self.period-(time.perf_counter()-began)))
        except Exception as exc:
            with self.condition:
                self.error=exc
                self.condition.notify_all()
            if self.on_failure is not None:self.on_failure(exc)
        finally:
            if source is not None:
                source.close()

    def read(self):
        with self.condition:
            while True:
                if self.stop.is_set() or self.local_stop.is_set():
                    raise InterruptedError('Capture stopped')
                if self.error is not None:
                    raise RuntimeError('Capture adapter failed') from self.error
                if self.latest is not None and self.latest.sequence>self.consumed:
                    p=self.latest
                    packet=FramePacket(p.image,p.sequence,p.captured_mono,p.captured_utc,p.read_ms,
                                       max(0,p.sequence-self.consumed-1),p.source_metrics)
                    self.consumed=p.sequence
                    return packet
                self.condition.wait(.05)

    def peek(self):
        """Non-consuming preview. Producer images are immutable after publication."""
        with self.condition:
            return self.latest

    def close(self):
        self.local_stop.set()
        with self.condition:
            self.condition.notify_all()
        self.thread.join()  # Owner remains alive; UI waits rather than leaking a device thread.
