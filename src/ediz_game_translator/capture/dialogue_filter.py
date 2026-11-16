"""Conservative spatial/structural HUD rejection; confidence is only one signal."""
import re
import math
from types import SimpleNamespace
from ediz_game_translator.core import clean_ocr, subtitle_observation

# Known short speech is permitted; arbitrary one/two-letter OCR noise is not.
SHORT_SPEECH = {'go','no','oh','hi','ok','yes','hey','thank you','thanks'}


def speech_phrase(text):
    return re.sub(r'[.!?,…]+$', '', text.strip()).casefold()


def dialogue_observation(result,width,height):
    texts=list(getattr(result,'txts',None) or [])
    scores=list(getattr(result,'scores',None) or [])
    boxes=getattr(result,'boxes',None)
    lines=[]; rejected=[]
    for i,raw in enumerate(texts):
        text=clean_ocr(str(raw))
        why=None
        if re.fullmatch(r'\d[\d., ]*\s*(?:m|km|ft|xp|%)',text,re.I):
            why='hud_distance'
        elif re.fullmatch(r'[A-Z][A-Z _]{2,24}',text):
            why='standalone_ui_label'
        elif (re.fullmatch(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}:?',text)
              and speech_phrase(text) not in SHORT_SPEECH):
            why='name_without_dialogue'
        box=None
        if boxes is not None and i<len(boxes):
            box=boxes[i]
            xs=[float(p[0]) for p in box]; ys=[float(p[1]) for p in box]
            x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys)
            if (x0+x1)/2 < .18*width or (x0+x1)/2 > .82*width:
                why='hud_side_position'
            geometry=(x0,x1,y0,y1)
        else:
            geometry=None
        if why:
            rejected.append(dict(index=i,reason=why))
        else:
            lines.append((i,text,float(scores[i]) if i<len(scores) else .7,box,geometry))
    # Group adjacent aligned lines around a central dialogue anchor. Do not join a
    # separate call/quest panel just because both are inside the crop.
    geometry_lines=[line for line in lines if line[4] is not None]
    if geometry_lines:
        def rank(line):
            text=line[1]; x0,x1,y0,y1=line[4]
            speaker=bool(re.match(r"^[\w .’'-]{2,32}:\s+\S",text))
            return (speaker, len(text.split())>=3, bool(re.search(r'[.!?]$',text)),
                    -abs((x0+x1)/2-width/2),y1)
        anchor=max(geometry_lines,key=rank)
        ax0,ax1,ay0,ay1=anchor[4]
        selected=[]
        for line in lines:
            g=line[4]
            aligned=g and (abs((g[0]+g[1]-ax0-ax1)/2)<=.16*width or abs(g[0]-ax0)<=.10*width)
            adjacent=g and max(0,g[2]-ay1,ay0-g[3])<=2.2*max(ay1-ay0,g[3]-g[2])
            if line is anchor or (aligned and adjacent): selected.append(line)
            else: rejected.append(dict(index=line[0],reason='separate_text_cluster'))
        lines=selected
    filtered=SimpleNamespace(txts=[x[1] for x in lines],scores=[x[2] for x in lines],
        boxes=[x[3] for x in lines] if lines and all(x[3] is not None for x in lines) else None)
    text,score=subtitle_observation(filtered,width)
    return text,score,dict(rejected=rejected,selected_indices=[x[0] for x in lines])


def dialogue_candidates(result,width,height):
    """Keep speaker boundaries before joining wrapped lines."""
    from ediz_game_translator.capture.subtitle_tracking import Candidate,SPEAKER,split_speaker
    _,_,evidence=dialogue_observation(result,width,height)
    texts=list(getattr(result,'txts',None) or [])
    scores=list(getattr(result,'scores',None) or [])
    boxes=getattr(result,'boxes',None)
    allowed=set(evidence['selected_indices'])
    spatial_only={r['index'] for r in evidence['rejected'] if r['reason']=='separate_text_cluster'}
    allowed.update(i for i in spatial_only if SPEAKER.match(clean_ocr(texts[i])))
    for i in tuple(allowed):
        _,line_body=split_speaker(clean_ocr(str(texts[i])))
        if (sum(c.isalpha() for c in line_body)<3 and re.search(r'[.!?]$',line_body)
                and speech_phrase(line_body) not in SHORT_SPEECH):
            allowed.remove(i)
            evidence['rejected'].append(dict(index=i,reason='short_ocr_noise'))
            continue
        score=float(scores[i]) if i<len(scores) else .7
        if not math.isfinite(score) or not .46<=score<=1:
            allowed.remove(i)
            evidence['rejected'].append(dict(index=i,reason='invalid_or_low_ocr_score'))
    def bounds(i):
        if boxes is None or i>=len(boxes):return None
        return (min(float(p[0]) for p in boxes[i]),max(float(p[0]) for p in boxes[i]),
                min(float(p[1]) for p in boxes[i]),max(float(p[1]) for p in boxes[i]))
    order=sorted(range(len(texts)),key=lambda i:(bounds(i)[2],bounds(i)[0]) if bounds(i) else (i,0))
    groups=[]; current=None
    for i in order:
        if i not in allowed:continue
        text=clean_ocr(str(texts[i])); matches=list(SPEAKER.finditer(text))
        pieces=[]
        if matches:
            if matches[0].start()>0:pieces.append(text[:matches[0].start()].strip())
            pieces.extend(text[m.start():(matches[j+1].start() if j+1<len(matches) else len(text))].strip()
                          for j,m in enumerate(matches))
        else:pieces=[text]
        for piece in pieces:
            speaker,body=split_speaker(piece)
            if speaker or current is None:
                current={'speaker':speaker,'texts':[],'scores':[],'boxes':[],'indices':[]}
                groups.append(current)
            current['texts'].append(piece if len(current['texts'])==0 else body if speaker else piece)
            current['scores'].append(float(scores[i]) if i<len(scores) else .7)
            current['indices'].append(i)
            if bounds(i):current['boxes'].append(bounds(i))
    candidates=[]
    for group in groups:
        text=clean_ocr(' '.join(group['texts']))
        speaker,body=split_speaker(text)
        if not body:continue
        if sum(c.isalpha() for c in body)<3:
            if speech_phrase(body) not in SHORT_SPEECH:
                evidence['rejected'].extend(dict(index=i,reason='short_ocr_noise') for i in group['indices'])
                continue
        b=group['boxes']
        box=(min(x[0] for x in b),max(x[1] for x in b),min(x[2] for x in b),max(x[3] for x in b)) if b else None
        candidates.append(Candidate(text,speaker,body,min(group['scores']),box,tuple(group['indices'])))
    return candidates,evidence
