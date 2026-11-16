"""Frame-normalized mask geometry shared by native, preview and browser views."""
from copy import deepcopy
import math
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


def arrange_blocks(blocks,style):
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
