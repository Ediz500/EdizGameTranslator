"""Generated video timeline + real RapidOCR. Not a PS5/capture-card recall test."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw,ImageFont
from capture_pipeline import CaptureRunner,DiagnosticLog
from frame_sources import FramePacket
from subtitle_store import SubtitleStore
from image_change import ImageChangeGate
from ocr_profiles import create_ocr
from subtitle_tracking import split_speaker
from local_benchmark import percentiles

LINES=['Go!','No!','Oh!','Hi!','Thank You','Mr. Fisk: Go!','Dr. Connors: No!',
       'MJ: We should leave now.','Go!','Stop!','Go!','Do not open the door.']


def key(text):
    return text.casefold().strip(' .!?,')


def run(ocr,mode,dwell,gap):
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',32)
    blank=Image.new('RGB',(960,160),'#20252d');images=[]
    for text in LINES:
        im=blank.copy();d=ImageDraw.Draw(im);d.text((480,80),text,font=font,fill='white',stroke_width=1,stroke_fill='black',anchor='mm');images.append(im)
    timeline=[];at=.25
    for i,line in enumerate(LINES):
        timeline.append((at,at+dwell,i));at+=dwell+gap
    elapsed=[0.];sequence=[0];events=[];ticks=[0];start=time.perf_counter();cpu=time.process_time()
    def frame():
        elapsed[0]=time.perf_counter()-start;sequence[0]+=1
        index=next((i for a,b,i in timeline if a<=elapsed[0]<b),None)
        return FramePacket(blank if index is None else images[index],sequence[0],time.perf_counter(),time.time(),0)
    gate=ImageChangeGate() if mode=='adaptive' else None
    interval=.28 if mode=='legacy280' else .04
    with tempfile.TemporaryDirectory() as folder:
        store=SubtitleStore(Path(folder)/'test.sqlite3')
        def accepted(row,text,when):events.append(dict(source=text,accepted=when-start))
        runner=CaptureRunner(frame,lambda im:im,ocr,store,'test',DiagnosticLog(),lambda:None,accepted,interval,gate)
        while time.perf_counter()-start<at+.2:
            delay=runner.step();time.sleep(delay)
        metrics=runner.metrics.summary();store.close()
    matched=set();delays=[];false=[];duplicate=[]
    for event in events:
        candidates=[(i,a,b) for a,b,i in timeline if key(event['source'])==key(LINES[i]) and a<=event['accepted']<=b+.4]
        if not candidates:false.append(event);continue
        i,a,b=min(candidates,key=lambda item:abs(event['accepted']-item[1]))
        if i in matched:duplicate.append(event)
        else:matched.add(i);delays.append((event['accepted']-a)*1000)
    return dict(mode=mode,expected=len(LINES),captured=len(matched),missed=len(LINES)-len(matched),
        false_accepts=len(false),duplicates=len(duplicate),generated_appearance_to_accept_ms=percentiles(delays),
        wall_seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu,ocr_calls=metrics['frames'],
        image_checks=gate.summary() if gate else None,ocr_ms=metrics['stages'].get('ocr_ms'),
        stages=metrics['stages'],events=events)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--profile',default='bounded960_cpu2')
    p.add_argument('--dwell',type=float,default=.25);p.add_argument('--gap',type=float,default=.10);a=p.parse_args()
    ocr=create_ocr(a.profile)
    warm=Image.new('RGB',(960,160),'black');draw=ImageDraw.Draw(warm)
    draw.text((80,50),'Mr. Fisk: Thank you. Go!',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',32),fill='white')
    for _ in range(2):ocr(warm)  # Warm detector AND text recognizer before every mode comparison.
    reports=[run(ocr,m,a.dwell,a.gap) for m in ('legacy280','fixed_fast','adaptive')]
    result=dict(kind='generated_images_real_ocr',physical_tv_verified=False,game_human_recall=None,
                profile=a.profile,dwell=a.dwell,gap=a.gap,reports=reports)
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))
