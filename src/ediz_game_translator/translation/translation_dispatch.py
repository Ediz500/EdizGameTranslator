"""Fixed-capacity dispatcher. SQLite journals work without serial completion gates."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from ediz_game_translator.capture.subtitle_tracking import split_speaker
from ediz_game_translator.translation.light_translation import WarmNMTClient
from ediz_game_translator.translation.translation_memory import SafeTranslationMemory


class LocalTranslationCoordinator:
    def __init__(self,settings,store,session,stop,on_result,on_error,engine_factory=WarmNMTClient):
        self.settings=settings;self.store=store;self.session=session;self.stop=stop
        self.on_result=on_result;self.on_error=on_error;self.engine_factory=engine_factory
        self.engine=None;self.lock=threading.Lock();self.active=0;self.peak_active=0
        self.completed=0;self.failed=0;self.init_ms=None
        self.memory=SafeTranslationMemory(settings['game'],settings['local_model_path'],settings.get('translation_pack') or None)

    def _loop(self):
        while not self.stop.is_set():
            job=self.store.claim_translation(self.session,time.monotonic())
            if job is None:
                with self.store.condition:self.store.condition.wait(.02)
                continue
            with self.lock:self.active+=1;self.peak_active=max(self.peak_active,self.active)
            try:
                began=time.monotonic();speaker,body=split_speaker(job['source'])
                context=self.store.context_before(job['id'])
                text,route=self.memory.lookup(body,speaker,context)
                timing={}
                if text is None:
                    result=self.engine.translate(body);text=result['text']
                    timing={k:result[k] for k in ('processing_ms','roundtrip_ms') if k in result}
                    self.memory.remember(body,speaker,context,text);route='local_model'
                ended=time.monotonic()
                timing.update(total_ms=(ended-began)*1000,capacity_wait_ms=(began-job['accepted_mono'])*1000)
                self.store.record_timing(job['id'],timing)
                self.store.complete_translation(job['id'],text,ended)
                with self.lock:self.completed+=1
                if not self.stop.is_set():self.on_result(job,text,ended-began,route)
            except Exception as exc:
                self.store.fail_translation(job['id'],time.monotonic())
                with self.lock:self.failed+=1
                self.on_error(str(exc))
                if getattr(self.engine,'closed',False):self.stop.set()
            finally:
                with self.lock:self.active-=1

    def run(self):
        try:
            began=time.monotonic()
            s=self.settings
            self.engine=self.engine_factory(s['local_python'],s['local_model_path'],device=s['local_device'],
                compute_type=s['local_compute_type'],workers=s['local_workers'],threads=s['local_threads'],
                beam_size=s.get('local_beam_size',4),stop_event=self.stop)
            self.init_ms=(time.monotonic()-began)*1000
            with ThreadPoolExecutor(max_workers=s['local_workers'],thread_name_prefix='local-dispatch') as pool:
                futures=[pool.submit(self._loop) for _ in range(s['local_workers'])]
                # Observe stop so a hung child is terminated before waiting for
                # executor shutdown, keeping GUI/capture shutdown bounded.
                while not self.stop.wait(.02):
                    if all(f.done() for f in futures):break
                self.engine.close()
                with self.store.condition:self.store.condition.notify_all()
                for f in futures:f.result()
        finally:
            if self.engine:self.engine.close()
            if self.stop.is_set():self.store.cancel_session(self.session,'local_session_end')

    def summary(self):
        return dict(engine_init_ms=self.init_ms,peak_active=self.peak_active,completed=self.completed,
                    failed=self.failed,capacity=self.settings['local_workers'])
