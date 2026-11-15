"""Warm, bounded, offline CTranslate2 worker. No cloud SDK or download path."""
import argparse
from concurrent.futures import Future,ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


class LocalEngineError(RuntimeError):pass


def validate_capacity(workers,threads,device):
    if type(workers) is not int or not 1<=workers<=4:raise ValueError('Yerel eşzamanlılık 1–4 olmalı.')
    if type(threads) is not int or not 1<=threads<=8:raise ValueError('CPU iş parçacığı sayısı 1–8 olmalı.')
    if workers*threads>max(1,min(16,os.cpu_count() or 1)):raise ValueError('CPU kapasitesi aşılıyor.')
    if device not in ('cpu','cuda'):raise ValueError('Aygıt cpu veya cuda olmalı.')
    if device=='cuda' and workers!=1:raise ValueError('GPU için bu sürümde eşzamanlılık 1 olmalı.')


def model_manifest(folder,verify=True):
    path=Path(folder).resolve()
    if not (path/'ediz_nmt.json').is_file():
        raise LocalEngineError('Yerel model bulunamadı. Model klasörünü seçin; otomatik indirme ve bulut fallback kapalı.')
    data=json.loads((path/'ediz_nmt.json').read_text(encoding='utf-8'))
    if data.get('engine') not in ('ct2-marian','argos-ct2') or (data.get('source_lang'),data.get('target_lang'))!=('en','tr'):
        raise LocalEngineError('Yalnız doğrulanmış doğrudan EN→TR modeli desteklenir.')
    for name in ('model.bin','source.spm','target.spm'):
        if not (path/name).is_file():raise LocalEngineError('Model dosyası eksik: '+name)
        if verify and hashlib.sha256((path/name).read_bytes()).hexdigest()!=data.get('files',{}).get(name):
            raise LocalEngineError('Model bütünlük kontrolü başarısız: '+name)
    return path,data


class WarmNMTClient:
    def __init__(self,python,folder,device='cpu',compute_type='int8',workers=2,threads=2,
                 request_timeout=15,load_timeout=120,on_start=None):
        validate_capacity(workers,threads,device)
        model_manifest(folder,verify=False)
        if not python or not Path(python).is_file():raise LocalEngineError('Yerel motor Python yolu bulunamadı.')
        self.lock=threading.RLock();self.write_lock=threading.Lock()
        self.pending={0:Future()};self.next_id=0;self.closed=False
        self.capacity=threading.BoundedSemaphore(workers);self.request_timeout=request_timeout
        script=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'light_translation.py'
        env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',
                 TOKENIZERS_PARALLELISM='false')
        self.process=subprocess.Popen([str(python),'-u',str(script),'--worker','--path',str(Path(folder).resolve()),
            '--device',device,'--compute-type',compute_type,'--workers',str(workers),'--threads',str(threads)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
            env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if on_start:on_start(self.process.pid)
        ready=self.pending[0]
        self.reader=threading.Thread(target=self._read,name='local-nmt-results',daemon=True);self.reader.start()
        try:self.ready=ready.result(timeout=load_timeout)
        except Exception as exc:
            self.close()
            if isinstance(exc,LocalEngineError):raise
            raise LocalEngineError('Yerel model yüklemesi zaman aşımına uğradı.') from None

    def _fail_all(self,message):
        with self.lock:
            self.closed=True
            futures=list(self.pending.values());self.pending.clear()
        for f in futures:
            if not f.done():f.set_exception(LocalEngineError(message))

    def _read(self):
        try:
            for line in self.process.stdout:
                try:response=json.loads(line)
                except ValueError:continue
                with self.lock:f=self.pending.pop(response.get('id'),None)
                if f is not None and not f.done():
                    if 'error' in response:f.set_exception(LocalEngineError(response['error']))
                    else:f.set_result(response)
        finally:self._fail_all('Yerel motor kapandı; otomatik bulut fallback yapılmadı.')

    def translate(self,text):
        if not isinstance(text,str) or not text.strip() or len(text)>360:raise ValueError('Altyazı 1–360 karakter olmalı.')
        if not self.capacity.acquire(timeout=self.request_timeout):raise LocalEngineError('Yerel motor kapasitesi dolu.')
        try:
            with self.lock:
                if self.closed:raise LocalEngineError('Yerel motor çalışmıyor.')
                self.next_id+=1;rid=self.next_id;f=Future();self.pending[rid]=f
            began=time.perf_counter()
            with self.write_lock:
                self.process.stdin.write(json.dumps(dict(id=rid,text=text))+'\n');self.process.stdin.flush()
            try:result=f.result(timeout=self.request_timeout)
            except TimeoutError:
                self.close();raise LocalEngineError('Yerel çeviri zaman aşımı; işçi kapatıldı.') from None
            result['roundtrip_ms']=(time.perf_counter()-began)*1000
            if not result.get('complete'):raise LocalEngineError('Yerel motor eksik/boş çeviri döndürdü.')
            return result
        except (BrokenPipeError,OSError):
            self.close();raise LocalEngineError('Yerel model bağlantısı kesildi.') from None
        finally:self.capacity.release()

    def close(self):
        self._fail_all('Yerel motor durduruldu.')
        p=self.process
        if p.poll() is None:
            p.terminate()
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)
        if threading.current_thread() is not self.reader:self.reader.join(timeout=2)
        for stream in (p.stdin,p.stdout):
            if stream:
                try:stream.close()
                except OSError:pass


class CT2Translator:
    def __init__(self,args):
        began=time.perf_counter();folder,self.manifest=model_manifest(args.path)
        import ctranslate2
        import sentencepiece
        supported=ctranslate2.get_supported_compute_types(args.device)
        if args.compute_type not in supported:raise LocalEngineError('İstenen compute_type aygıtta desteklenmiyor.')
        os.chdir(folder)  # Child process only; keep native Windows paths ASCII-relative.
        self.model=ctranslate2.Translator('.',device=args.device,compute_type=args.compute_type,
            inter_threads=args.workers,intra_threads=args.threads,max_queued_batches=args.workers)
        self.source=sentencepiece.SentencePieceProcessor(model_proto=(folder/'source.spm').read_bytes())
        self.target=sentencepiece.SentencePieceProcessor(model_proto=(folder/'target.spm').read_bytes())
        self.load_ms=(time.perf_counter()-began)*1000
        self.runtime=dict(ctranslate2=ctranslate2.__version__,device=args.device,compute_type=args.compute_type,
                          workers=args.workers,threads=args.threads)

    def translate(self,text):
        began=time.perf_counter();tokens=self.source.encode(text,out_type=str)+['</s>']
        if len(tokens)>256:raise ValueError('Kaynak token sınırını aşıyor; sessiz kırpma yapılmadı.')
        answer=self.model.translate_batch([tokens],beam_size=1,max_decoding_length=256,
            max_input_length=0,return_end_token=False)[0].hypotheses[0]
        result=self.target.decode(answer).strip()
        return dict(text=result,complete=bool(result) and len(answer)<256,output_tokens=len(answer),
                    processing_ms=(time.perf_counter()-began)*1000)


def worker(args):
    validate_capacity(args.workers,args.threads,args.device)
    protocol=sys.stdout;lock=threading.Lock()
    def send(value):
        with lock:protocol.write(json.dumps(value,ensure_ascii=False)+'\n');protocol.flush()
    try:
        engine=CT2Translator(args)
        warm=time.perf_counter();engine.translate('Please wait here.')
        send(dict(id=0,ready=True,load_ms=engine.load_ms,warmup_ms=(time.perf_counter()-warm)*1000,
                  runtime=engine.runtime,manifest=engine.manifest))
        slots=threading.BoundedSemaphore(args.workers)
        def run(request):
            try:
                text=request['text']
                if not isinstance(text,str) or not text.strip() or len(text)>360:raise ValueError('Invalid source')
                send(dict(id=request['id'],**engine.translate(text)))
            except Exception as exc:send(dict(id=request.get('id'),error=f'{type(exc).__name__}: {str(exc)[:300]}'))
            finally:slots.release()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for line in sys.stdin:
                request=json.loads(line)
                if not slots.acquire(blocking=False):
                    send(dict(id=request.get('id'),error='Yerel motor kapasitesi dolu.'));continue
                pool.submit(run,request)
    except Exception as exc:send(dict(id=0,error=f'{type(exc).__name__}: {str(exc)[:300]}'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',required=True,action='store_true')
    p.add_argument('--path',required=True);p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    p.add_argument('--compute-type',default='int8');p.add_argument('--workers',type=int,default=2)
    p.add_argument('--threads',type=int,default=2);worker(p.parse_args())
