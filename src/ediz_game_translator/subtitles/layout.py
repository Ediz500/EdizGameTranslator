"""Frame-normalized mask geometry shared by native, preview and browser views."""
from copy import deepcopy
import math
import time
from ediz_game_translator.storage.subtitle_styles import valid_style


def contain(view_width,view_height,source_width=1920,source_height=1080):
    scale=min(view_width/source_width,view_height/source_height)
    return ((view_width-source_width*scale)/2,(view_height-source_height*scale)/2,
            source_width*scale,source_height*scale)


def viewport_rect(rect,view_width,view_height,source_size=(1920,1080)):
    x,y,w,h=contain(view_width,view_height,*source_size)
    return (x+rect[0]*w,y+rect[1]*h,x+rect[2]*w,y+rect[3]*h)


def bounded_rect(cx,bottom,width,height):
    width=min(1,max(.05,width));height=min(1,max(.025,height))
    left=max(0,min(1-width,cx-width/2));top=max(0,min(1-height,bottom-height))
    return [left,top,left+width,top+height]


def _fixed_layout(blocks,style):
    style=valid_style(style);result=[]
    for block in blocks[:3]:
        b=deepcopy(block);fallback=style['mask_rect'];bounds=b.get('bounds')
        width=fallback[2]-fallback[0];height=fallback[3]-fallback[1]
        cx=(fallback[0]+fallback[2])/2;bottom=fallback[3]
        if style['position']=='auto' and bounds:
            cx=(bounds[0]+bounds[2])/2;bottom=min(1,bounds[3]+.008)
            width=max(width,bounds[2]-bounds[0]+.02)
            height=max(bounds[3]-bounds[1]+.016,.045)
        chars_per_line=max(8,(width*1920-40)/(style['font_size']*.56))
        lines=max(1,math.ceil(len(b['text'])/chars_per_line))
        name=style['show_speaker'] and bool(b.get('speaker'))
        needed=(lines*style['font_size']*1.28+(style['font_size']*.7 if name else 0)+24)/1080
        height=max(height,needed)
        b['mask_rect']=bounded_rect(cx,bottom,width,height)
        result.append(b)
    # Overlapping source rows share an opaque union but keep separate text/name
    # blocks. There are no presentation slots or reading timers.
    groups=[]
    for b in result:
        rect=b['mask_rect'];touch=[]
        for group in groups:
            if any(min(rect[2],a['mask_rect'][2])>max(rect[0],a['mask_rect'][0]) and
                   min(rect[3],a['mask_rect'][3])>max(rect[1],a['mask_rect'][1]) for a in group):touch.append(group)
        merged=[b]
        for group in touch:merged+=group;groups.remove(group)
        groups.append(merged)
    for group in groups:
        if len(group)<2:continue
        group.sort(key=lambda b:(b.get('bounds') or b['mask_rect'])[1])
        left=min(b['mask_rect'][0] for b in group);right=max(b['mask_rect'][2] for b in group)
        bottom=max(b['mask_rect'][3] for b in group)
        heights=[b['mask_rect'][3]-b['mask_rect'][1] for b in group]
        if sum(heights)>1:
            scale=1/sum(heights);heights=[h*scale for h in heights]
            for b in group:b['font_scale']=scale
        total=min(1,sum(heights));top=max(0,min(min(b['mask_rect'][1] for b in group),bottom-total))
        for b,height in zip(group,heights):
            next_top=min(1,top+height);b['mask_rect']=[left,top,right,next_top];top=next_top
    return result


# Use the installed Windows font; never download or package licensed system fonts.
from functools import lru_cache
from pathlib import Path
from PIL import ImageFont


@lru_cache(maxsize=96)
def _font(size):
    path=Path('C:/Windows/Fonts/segoeuib.ttf')
    try:return ImageFont.truetype(str(path),size)
    except OSError:return None


def _wrap(text,font,width):
    lines=[]
    for paragraph in text.split('\n'):
        line=''
        for word in paragraph.split():
            trial=(line+' '+word).strip()
            if font.getlength(trial)*1.03<=width:line=trial;continue
            if line:lines.append(line);line=''
            for char in word:
                if line and font.getlength(line+char)*1.03>width:lines.append(line);line=''
                line+=char
        lines.append(line)
    return lines or ['']


@lru_cache(maxsize=256)
def _measured(text,speaker,show,size,width):
    font=_font(size);name_font=_font(max(6,round(size*.7)))
    lines=_wrap(text,font,width)
    names=_wrap(speaker,name_font,width) if show and speaker else []
    measured=max([font.getlength(line)*1.03 for line in lines]+[name_font.getlength(n)*1.03 for n in names]+[1])
    return dict(display_lines=lines,name_lines=names,visual_font_size=size,
        body_height=len(lines)*math.ceil(size*1.28)/1080,
        name_height=len(names)*math.ceil(max(6,round(size*.7))*1.28)/1080,
        measured_width=measured/1920)


def _content(block,style,size,width):
    return deepcopy(_measured(block['text'],block.get('speaker',''),style['show_speaker'],size,round(width,3)))


def _fallback(block,style):
    original=deepcopy(block);original['bounds']=None
    b=_fixed_layout([original],style)[0];r=b['mask_rect'];size=style['font_size']
    while True:
        c=_content(b,style,size,max(10,(r[2]-r[0])*1920-36))
        if c['body_height']+c['name_height']+18/1080<=r[3]-r[1] or size<=8:break
        size-=1
    b.update(c);bottom=r[3]-8/1080;top=bottom-c['body_height']
    b['body_rect']=[r[0]+18/1920,top,r[2]-18/1920,bottom]
    b['name_rect']=[r[0]+18/1920,top-c['name_height']-2/1080,r[2]-18/1920,top-2/1080]
    return b


def _trusted(bounds,size):
    return (isinstance(bounds,(list,tuple)) and len(bounds)==4 and len(size)==2 and min(size)>0
        and all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in bounds)
        and 1/size[0]<=bounds[2]-bounds[0]<=1 and 1/size[1]<=bounds[3]-bounds[1]<=.35)


def _union(a,b):return [min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]


def _padded(rect,x,y):return [max(0,rect[0]-x),max(0,rect[1]-y),min(1,rect[2]+x),min(1,rect[3]+y)]


class VisualLayout:
    """Per visible job locks. Raw OCR and translation storage remain untouched."""
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.generation=None;self.locks={};self.style_key=None;self.recent={}

    def reset(self):self.locks.clear();self.recent.clear();self.generation=None;self.style_key=None

    def arrange(self,blocks,style,generation=None):
        style=valid_style(style)
        key=(style['font_size'],tuple(style['mask_rect']),style['position'])
        if generation!=self.generation or key!=self.style_key:
            self.reset();self.generation=generation;self.style_key=key
        if style['position']=='fixed' or _font(style['font_size']) is None:return _fixed_layout(blocks,style)
        now=self.clock();self.recent={k:v for k,v in self.recent.items() if now-v[2]<=.35}
        result=[];active=set()
        for b in blocks[:3]:
            size=b.get('source_size',(1920,1080));bounds=b.get('bounds')
            if not _trusted(bounds,size) or _font(style['font_size']) is None:
                result.append(_fallback(b,style) if _font(style['font_size']) is not None else _fixed_layout([b],style)[0]);continue
            identity=(b.get('subtitle_id',b['id']),b['id']);active.add(identity)
            if identity not in self.locks:
                # Reserve six source pixels: +/- five-pixel OCR noise needs no move.
                margin_x=max(12/1920,6/size[0]);margin_y=max(8/1080,6/size[1])
                limit=max(bounds[2]-bounds[0],min(.86,max(.18,style['mask_rect'][2]-style['mask_rect'][0])))
                anchor=list(bounds)
                # OCR variants can create a fresh job. Carry only nearby geometry,
                # never text, masks or visibility, across a <=350 ms display gap.
                for previous,previous_size,seen in reversed(list(self.recent.values())):
                    if tuple(size)==previous_size and all(abs(bounds[i]-previous[i])<=5/size[i%2]+1e-10 for i in range(4)):
                        anchor=list(previous);break
                self.locks[identity]=dict(anchor=anchor,envelope=_padded(anchor,margin_x,margin_y),
                    limit=max(40,limit*1920-36),margin=(margin_x,margin_y),mask=None)
            lock=self.locks[identity];envelope=lock['envelope']
            self.recent.pop(identity,None);self.recent[identity]=(list(lock['anchor']),tuple(size),now)
            self.recent=dict(list(self.recent.items())[-6:])
            # Inside the reserved dead zone, no geometry changes at all. Outside,
            # expand coverage immediately while retaining the body anchor.
            if not(envelope[0]<=bounds[0] and envelope[1]<=bounds[1] and bounds[2]<=envelope[2] and bounds[3]<=envelope[3]):
                lock['envelope']=_union(envelope,_padded(bounds,*lock['margin']))
            result.append(self._single(b,style,lock))
        self.locks={k:v for k,v in self.locks.items() if k in active}
        self._pack(result,style)
        return result

    def _single(self,block,style,lock):
        b=deepcopy(block);a=lock['anchor'];size=style['font_size']
        while True:
            content=_content(b,style,size,lock['limit'])
            if content['body_height']+content['name_height']+18/1080<=1 or size<=8:break
            size-=1
        b.update(content);width=max(a[2]-a[0],content['measured_width'])
        width=min(1-36/1920,width);cx=(a[0]+a[2])/2
        left=max(18/1920,min(1-18/1920-width,cx-width/2))
        bottom=min(1-8/1080,max(a[3],content['body_height']+content['name_height']+10/1080))
        b['body_rect']=[left,bottom-content['body_height'],left+width,bottom]
        top=b['body_rect'][1]-content['name_height']-(2/1080 if content['name_height'] else 0)
        b['name_rect']=[left,top,left+width,b['body_rect'][1]-(2/1080 if content['name_height'] else 0)]
        text_box=[left,top,left+width,bottom]
        mask=_union(lock['envelope'],_padded(text_box,18/1920,8/1080))
        # Never shrink a mask while the same translated job remains visible.
        lock['mask']=_union(lock['mask'],mask) if lock['mask'] else mask
        b['mask_rect']=list(lock['mask']);return b

    def _pack(self,blocks,style):
        groups=[]
        for b in blocks:
            if 'body_rect' not in b:continue
            r=b['mask_rect'];touch=[g for g in groups if any(min(r[2],a['mask_rect'][2])>max(r[0],a['mask_rect'][0]) and min(r[3],a['mask_rect'][3])>max(r[1],a['mask_rect'][1]) for a in g)]
            merged=[b]
            for g in touch:merged+=g;groups.remove(g)
            groups.append(merged)
        for group in groups:
            if len(group)<2:continue
            group.sort(key=lambda b:(b['body_rect'][3],b['id']))
            union=group[0]['mask_rect']
            for b in group[1:]:union=_union(union,b['mask_rect'])
            width=max(40,(union[2]-union[0])*1920-36);font=min(b['visual_font_size'] for b in group)
            while True:
                contents=[_content(b,style,font,width) for b in group]
                reserve=math.ceil(max(6,round(font*.7))*1.28)/1080 if style['show_speaker'] else 0
                heights=[c['body_height']+max(c['name_height'],reserve)+18/1080 for c in contents]
                if sum(heights)<=1 or font<=8:break
                font-=1
            total=sum(heights);top=max(0,min(union[1],union[3]-total));bottom=min(1,max(union[3],top+total))
            mask=[union[0],top,union[2],bottom];y=top
            for b,c,h in zip(group,contents,heights):
                b.update(c);name_height=max(c['name_height'],reserve)
                b['mask_rect']=list(mask)
                b['name_rect']=[mask[0]+18/1920,y+8/1080,mask[2]-18/1920,y+8/1080+name_height]
                start=y+8/1080+name_height+2/1080
                b['body_rect']=[mask[0]+18/1920,start,mask[2]-18/1920,start+c['body_height']]
                y+=h


def arrange_blocks(blocks,style):
    """Stateless preview helper; the live server owns a persistent VisualLayout."""
    return VisualLayout().arrange(blocks,style)


def visual_signature(blocks):
    """Only visible geometry/content; raw OCR boxes and ACK times are not paint."""
    fields=('id','text','speaker','mask_rect','body_rect','name_rect','display_lines',
            'name_lines','visual_font_size','font_scale','source_size')
    return tuple(repr(tuple(b.get(key) for key in fields)) for b in blocks)
