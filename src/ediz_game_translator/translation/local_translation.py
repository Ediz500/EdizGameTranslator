"""Offline-only translation worker. Never imports OpenAI or touches app settings.

This is benchmark infrastructure, not an enabled/quality-approved GUI engine.
Model files must already exist locally with an explicit provenance manifest.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

LOCAL_MODELS = {
    'milmmt-1b': 'xiaomi-research/MiLMMT-46-1B-v1.0',
    'milmmt-4b': 'xiaomi-research/MiLMMT-46-4B-v1.0',
    'translategemma-4b': 'google/translategemma-4b-it',
    'translategemma-12b': 'google/translategemma-12b-it',
}


def milmmt_prompt(text):
    return f'Translate this from English to Turkish:\nEnglish: {text}\nTurkish:'


def gemma_messages(text):
    return [{'role': 'user', 'content': [{'type': 'text', 'source_lang_code': 'en',
             'target_lang_code': 'tr', 'text': text}]}]


def experimental_gemma_prompt(text, context):
    # Official card explicitly calls alternate prompts unsupported/experimental.
    return ('<bos><start_of_turn>user\nTranslate only CURRENT from English to Turkish. '
            'PREVIOUS is context, do not translate it. Output only the translation.\n'
            f'PREVIOUS:\n{context}\nCURRENT:\n{text}<end_of_turn>\n<start_of_turn>model\n')


def check_model_path(key, folder):
    if key not in LOCAL_MODELS:raise ValueError('Unsupported translation checkpoint')
    path=Path(folder).resolve()
    if not path.is_dir():raise FileNotFoundError('Yerel model klasörü bulunamadı; otomatik indirme kapalı.')
    manifest=json.loads((path/'ediz_model.json').read_text(encoding='utf-8'))
    if manifest.get('model_id')!=LOCAL_MODELS[key] or not manifest.get('revision'):
        raise ValueError('Çeviri modeli kimliği/sürümü doğrulanamadı.')
    return path,manifest


class LocalWorkerError(RuntimeError):pass


class LocalWorkerClient:
    """One warm child per benchmark; timeout/crash kills only the child."""
    def __init__(self, python, key, folder, precision='nf4', load_timeout=180, request_timeout=30,on_start=None):
        self.process=None;self.messages=queue.Queue();self.request_timeout=request_timeout
        check_model_path(key,folder)
        env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false',
                 PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
        command=[str(python),'-u',str(Path(__file__).resolve()),'--worker','--model',key,
                 '--path',str(Path(folder).resolve()),'--precision',precision]
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env=env,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if on_start:on_start(self.process.pid)
        threading.Thread(target=self._read,daemon=True).start()
        try:self.ready=self._receive(load_timeout)
        except Exception:self.close();raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try:self.messages.put(json.loads(line))
                except ValueError:continue
        finally:self.messages.put({'error':'Yerel işçi beklenmedik biçimde kapandı.'})

    def _receive(self, timeout):
        try:response=self.messages.get(timeout=timeout)
        except queue.Empty:
            self.close();raise LocalWorkerError('Yerel model zaman aşımı; işçi kapatıldı.') from None
        if 'error' in response:raise LocalWorkerError(response['error'])
        return response

    def translate(self,text,context='',experimental=False):
        if not text.strip() or len(text)>360:raise ValueError('Altyazı 1–360 karakter olmalı.')
        try:
            self.process.stdin.write(json.dumps(dict(text=text,context=context,experimental=experimental))+'\n')
            self.process.stdin.flush()
            return self._receive(self.request_timeout)
        except Exception:
            self.close();raise

    def close(self):
        p=self.process
        if p is None:return
        if p.poll() is None:
            p.terminate()
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)
        for stream in (p.stdin,p.stdout):
            if stream:
                try:stream.close()
                except OSError:pass


class OfflineTranslator:
    def __init__(self,key,folder,precision):
        # Import cost is part of cold load time, before CUDA synchronization.
        started=time.perf_counter()
        folder,self.manifest=check_model_path(key,folder)
        import torch
        from transformers import AutoConfig,AutoTokenizer,AutoModelForCausalLM,AutoModelForImageTextToText,BitsAndBytesConfig
        self.torch=torch;self.key=key
        if not torch.cuda.is_available():raise RuntimeError('CUDA kullanılamıyor; CPU fallback kapalı.')
        dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        kwargs=dict(local_files_only=True,trust_remote_code=False,device_map={'':0},dtype=dtype,
                    attn_implementation='sdpa')
        if precision=='nf4':
            kwargs['quantization_config']=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',
                bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=dtype)
        self.tokenizer=AutoTokenizer.from_pretrained(folder,local_files_only=True,trust_remote_code=False)
        config=AutoConfig.from_pretrained(folder,local_files_only=True,trust_remote_code=False)
        # Both 4B checkpoints have Gemma3 multimodal architectures. Do not rely
        # on the model card's generic CausalLM example for those checkpoints.
        cls=AutoModelForImageTextToText if config.model_type=='gemma3' else AutoModelForCausalLM
        self.model=cls.from_pretrained(folder,**kwargs).eval()
        torch.cuda.synchronize()
        self.load_ms=(time.perf_counter()-started)*1000
        self.precision=precision
        from importlib.metadata import version
        self.runtime=dict(torch=torch.__version__,transformers=version('transformers'),
            cuda_runtime=torch.version.cuda,gpu=torch.cuda.get_device_name(0),dtype=str(dtype),
            gpu_total_mib=torch.cuda.get_device_properties(0).total_memory/2**20,
            bitsandbytes=version('bitsandbytes') if precision=='nf4' else None)

    def translate(self,text,context='',experimental=False):
        torch=self.torch
        if experimental and not self.key.startswith('translategemma'):raise ValueError('Context experiment only supports TranslateGemma')
        torch.cuda.synchronize();started=time.perf_counter()
        if self.key.startswith('milmmt'):
            inputs=self.tokenizer(milmmt_prompt(text),add_special_tokens=False,return_tensors='pt')
        elif experimental:
            inputs=self.tokenizer(experimental_gemma_prompt(text,context),add_special_tokens=False,return_tensors='pt')
        else:
            inputs=self.tokenizer.apply_chat_template(gemma_messages(text),tokenize=True,
                add_generation_prompt=True,return_dict=True,return_tensors='pt')
        inputs=inputs.to('cuda:0');input_len=inputs['input_ids'].shape[-1]
        if input_len>1536:raise ValueError('Girdi bağlam sınırını aşıyor.')
        torch.cuda.reset_peak_memory_stats()
        prepared=time.perf_counter()
        with torch.inference_mode():
            output=self.model.generate(**inputs,max_new_tokens=250,do_sample=False,use_cache=True)
        torch.cuda.synchronize();generated=time.perf_counter()
        tokens=output[0][input_len:]
        result=self.tokenizer.decode(tokens,skip_special_tokens=True).strip()
        eos=self.model.generation_config.eos_token_id
        eos=[eos] if isinstance(eos,int) else (eos or [])
        truncated=len(tokens)>=250 and (not len(tokens) or int(tokens[-1]) not in eos)
        # Never present a capped generation as a complete Turkish sentence.
        complete=bool(result) and not truncated
        return dict(text=result,complete=complete,truncated=truncated,output_tokens=len(tokens),
            prepare_ms=(prepared-started)*1000,generation_ms=(generated-prepared)*1000,
            full_sentence_ms=(time.perf_counter()-started)*1000,
            vram_allocated_mib=torch.cuda.max_memory_allocated()/2**20,
            vram_reserved_mib=torch.cuda.max_memory_reserved()/2**20,
            experimental_context=experimental)


def worker(args):
    protocol=sys.stdout
    # Keep dependency logging off the JSON protocol channel.
    from contextlib import redirect_stdout
    def send(data):protocol.write(json.dumps(data,ensure_ascii=False)+'\n');protocol.flush()
    try:
        with redirect_stdout(sys.stderr):engine=OfflineTranslator(args.model,args.path,args.precision)
        send(dict(ready=True,load_ms=engine.load_ms,manifest=engine.manifest,precision=args.precision,runtime=engine.runtime))
        for line in sys.stdin:
            try:
                request=json.loads(line)
                text=request['text']
                if not isinstance(text,str) or not text.strip() or len(text)>360:raise ValueError('Invalid source')
                with redirect_stdout(sys.stderr):result=engine.translate(text,request.get('context',''),request.get('experimental',False))
                send(result)
            except Exception as exc:
                send({'error':f'{type(exc).__name__}: {str(exc)[:350]}'})
                break
    except Exception as exc:send({'error':f'{type(exc).__name__}: {str(exc)[:350]}'})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true',required=True)
    p.add_argument('--model',choices=LOCAL_MODELS,required=True);p.add_argument('--path',required=True)
    p.add_argument('--precision',choices=['nf4','bf16'],default='nf4');worker(p.parse_args())
