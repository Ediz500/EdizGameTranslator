"""Short, per-track visual support for OCR dropouts; never a translation cache."""
from dataclasses import replace
import re
import numpy as np
import cv2
from ediz_game_translator.capture.subtitle_tracking import equivalent,position_matches


HOLD_SECONDS=.45


def narrow_glyph_variant(a,b):
    """Only an isolated I/l/Il pronoun before a verb; no fuzzy word matching."""
    if min(len(a),len(b))<18 or min(len(a.split()),len(b.split()))<4:return False
    verb=r"(?:am|was|have|had|got|get|need|think|guess|learned|suspect|can|could|did|do|will|would|want|should|heard|know|dunno)\b"
    pattern=r"(?<![\w'])\b(?:I|l|Il)\b(?=\s+"+verb+r")"
    bb=re.sub(pattern,'I',b)
    # Only support a previously read, correct pronoun. An initially damaged
    # proper noun / OCR reading must never become the canonical reference.
    return re.sub(pattern,'I',a)==a and bb!=b and equivalent(a,bb)


def _dilate(mask):
    padded=np.pad(mask,1);result=np.zeros_like(mask)
    for dy in range(3):
        for dx in range(3):result|=padded[dy:dy+mask.shape[0],dx:dx+mask.shape[1]]
    return result


def _masks(rgb):
    high=rgb.max(axis=2);low=rgb.min(axis=2)
    bright=(low>=210)|((high>=170)&(high-low>=60))
    dark=rgb.max(axis=2)<100
    glyph=bright&_dilate(_dilate(dark))
    return glyph,dark,bright


class SourceEvidence:
    def __init__(self,debounce=.12):self.debounce=debounce;self.references={};self.last_events=[]

    def _same(self,key,image,now):
        ref=self.references.get(key)
        if ref is None:return False
        if not 0<=now-ref['ocr_mono']<=HOLD_SECONDS:return False
        l,t,r,b=ref['rect'];patch=np.asarray(image.crop((l,t,r,b)).convert('RGB'))
        if patch.shape!=ref['shape']:return False
        _,dark,bright=_masks(patch);glyph=ref['glyph'];outline=ref['outline'];best=0
        # Compression / camera conversion can move a glyph by one source pixel.
        for dy in (-1,0,1):
            for dx in (-1,0,1):
                cur=np.roll(bright,(dy,dx),(0,1));neg=np.roll(dark,(dy,dx),(0,1))
                support=np.count_nonzero(cur&glyph)/ref['pixels']
                if support<.97:continue
                if outline.any() and np.count_nonzero(neg&outline)/np.count_nonzero(outline)<.90:continue
                local=True
                for y,x,count in ref['tiles']:
                    matched=np.count_nonzero(cur[y:y+6,x:x+6]&glyph[y:y+6,x:x+6])
                    if count-matched>max(1,int(count*.15)):
                        local=False;break
                if local:best=max(best,support)
        return bool(best>=.97)

    def reconcile(self,candidates,tracks,image,now):
        """Return tracking inputs plus audit metadata; raw OCR is never rewritten."""
        self.last_events=[];output=list(candidates);originals={};held=set()
        def ended(t):
            return t.retired or (t.missed>=2 and t.absent_since is not None and now-t.absent_since>=self.debounce)
        for index,c in enumerate(candidates):
            for t in tracks:
                if not t.accepted or ended(t) or t.row is None or t.box is None or c.box is None or t.speaker!=c.speaker or not position_matches(t.box,c.box):continue
                if narrow_glyph_variant(t.body,c.body) and self._same(t.key,image,now):
                    output[index]=replace(c,text=t.current_text,body=t.body)
                    originals[t.key]=c;held.add(t.key)
                    self.last_events.append(dict(track=t.key,reason='image_supported_glyph'))
                    break
        for t in tracks:
            if not t.accepted or ended(t) or t.row is None or t.key in held:continue
            if any(c.speaker.casefold()==t.speaker.casefold() and position_matches(t.box,c.box) and equivalent(t.body,c.body) for c in output):continue
            # A new readable line/speaker in this slot always wins over old evidence.
            if any(position_matches(t.box,c.box) for c in output):continue
            if self._same(t.key,image,now):
                from ediz_game_translator.capture.subtitle_tracking import Candidate
                output.append(Candidate(t.current_text,t.speaker,t.body,t.confidence,t.box))
                held.add(t.key);self.last_events.append(dict(track=t.key,reason='image_supported_dropout'))
        active={t.key for t in tracks if not t.retired}
        self.references={k:v for k,v in self.references.items() if k in active and 0<=now-v['ocr_mono']<=HOLD_SECONDS}
        return output,originals,held

    def observe(self,actions,image,now,raw_boxes=None,held=()):
        for action in actions:
            t=action.track;c=action.candidate
            if t.key in held or not t.accepted or t.box is None:continue
            x0,x1,y0,y1=t.box
            l=max(0,int(x0)-2);r=min(image.width,int(x1)+3);top=max(0,int(y0)-2);bottom=min(image.height,int(y1)+3)
            if r<=l or bottom<=top:continue
            previous=self.references.get(t.key)
            if previous and equivalent(previous['text'],c.text) and abs(l-previous['rect'][0])<=5 and abs(top-previous['rect'][1])<=5 and abs(r-previous['rect'][2])<=5 and abs(bottom-previous['rect'][3])<=5:
                l,top,r,bottom=previous['rect']
            else:previous=None
            patch=np.asarray(image.crop((l,top,r,bottom)).convert('RGB'));glyph,dark,_=_masks(patch)
            if raw_boxes is not None and c.indices:
                allowed=np.zeros_like(glyph)
                for i in c.indices:
                    if i>=len(raw_boxes):continue
                    box=raw_boxes[i];xs=[float(p[0]) for p in box];ys=[float(p[1]) for p in box]
                    a=max(0,int(min(xs))-l);b=min(r-l,int(max(xs))-l+1)
                    u=max(0,int(min(ys))-top);v=min(bottom-top,int(max(ys))-top+1)
                    allowed[u:v,a:b]=True
                glyph&=allowed
            # Keep only strokes confirmed in successive OCR-positive images.
            # Moving scenery inside the line boxes must not become source proof.
            if previous and previous['shape']==patch.shape:
                glyph&=previous['glyph'];dark&=previous['dark']
            _,labels,stats,_=cv2.connectedComponentsWithStats(glyph.astype(np.uint8),connectivity=8)
            sizes=stats[:,cv2.CC_STAT_AREA];sizes[0]=0;glyph=sizes[labels]>=4
            count=np.count_nonzero(glyph)
            if count<12:continue
            outline=dark&_dilate(glyph);tiles=[]
            for y in range(0,glyph.shape[0],6):
                for x in range(0,glyph.shape[1],6):
                    n=np.count_nonzero(glyph[y:y+6,x:x+6])
                    if n>=6:tiles.append((y,x,n))
            self.references[t.key]=dict(rect=(l,top,r,bottom),shape=patch.shape,glyph=glyph,outline=outline,pixels=count,tiles=tiles,ocr_mono=now,text=c.text,dark=dark)
