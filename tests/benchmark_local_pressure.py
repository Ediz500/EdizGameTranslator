"""Opt-in real model with continuously running synthetic-image OCR; OBS read-only."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw,ImageFont
from ocr_profiles import create_ocr
from benchmark_light import benchmark


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--python',required=True);p.add_argument('--model-path',required=True)
    p.add_argument('--corpus',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    if Path(a.output).exists():raise FileExistsError('Choose a new report')
    import psutil
    if not any((r.info['name'] or '').casefold()=='obs64.exe' for r in psutil.process_iter(['name'])):
        raise RuntimeError('OBS must already be running; this tool never starts or reconfigures it.')
    ocr=create_ocr('bounded960_cpu2');image=Image.new('RGB',(960,160),'#20252d')
    ImageDraw.Draw(image).text((100,50),'MJ: We should leave before the guards return.',fill='white',
        font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',32))
    for _ in range(2):ocr(image)
    stop=threading.Event();cycles=[];errors=[]
    def loop():
        try:
            while not stop.is_set():
                began=time.perf_counter();ocr(image);cycles.append((time.perf_counter()-began)*1000)
                stop.wait(max(0,.04-(time.perf_counter()-began)))
        except Exception as exc:errors.append(type(exc).__name__)
    thread=threading.Thread(target=loop);thread.start()
    try:
        a.device='cuda';a.compute_type='int8_float16';a.workers=1;a.threads=2;a.repeats=3
        a.beam_size=4;a.parallel=False;a.workload='obs-ocr'
        report=benchmark(a)
    finally:stop.set();thread.join(5)
    report.update(synthetic_ocr_pressure=True,ocr_cycles=len(cycles),ocr_errors=errors,
        workload_verified=bool(cycles) and not errors and 'obs64.exe' in report['observed_process_names'])
    report['limitation']+=' OCR images are generated, not captured PS5 video. OBS process presence does not establish recording/encoding load.'
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
