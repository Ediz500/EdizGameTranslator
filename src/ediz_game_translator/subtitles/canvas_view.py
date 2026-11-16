"""Canvas rendering shared by the native output and the application's previews."""
from ediz_game_translator.subtitles.layout import viewport_rect,contain
from ediz_game_translator.storage.subtitle_styles import DEFAULT_STYLE


def draw_captions(canvas,blocks,style=None,width=None,height=None):
    style=style or DEFAULT_STYLE
    width=width or canvas.winfo_width();height=height or canvas.winfo_height()
    canvas.delete('caption')
    for i,b in enumerate(blocks):
        source=b.get('source_size',(1920,1080));rect=b.get('mask_rect',style['mask_rect'])
        l,t,r,bottom=viewport_rect(rect,width,height,source)
        k=contain(width,height,*source)[2]/1920
        pad=max(3,18*k);available=max(4,r-l-2*pad);h=bottom-t
        canvas.create_rectangle(l,t,r,bottom,fill='#000000',outline='',tags=('caption','mask'))
        if 'body_rect' in b:
            size=max(1,round(b['visual_font_size']*k))
            align=style['alignment'];anchor={'left':'nw','center':'n','right':'ne'}[align]
            def text_at(rect,lines,pixels,color,tag):
                x0,y0,x1,y1=viewport_rect(rect,width,height,source)
                x={'left':x0,'center':(x0+x1)/2,'right':x1}[align]
                # Explicit measured lines: Tk must not invent a different wrap.
                line_height=max(1,round(pixels*1.28))
                for line_no,line in enumerate(lines):
                    self_tag=f'caption_text_{i}'
                    canvas.create_text(x,y0+line_no*line_height,anchor=anchor,text=line,
                        font=('Segoe UI',-pixels,'bold'),fill=color,justify=align,
                        tags=('caption',self_tag,tag))
            text_at(b['body_rect'],b['display_lines'],size,'#FFFFFF','dialogue')
            if style['show_speaker'] and b.get('speaker'):
                name_size=max(1,round(max(6,round(b['visual_font_size']*.7))*k))
                text_at(b['name_rect'],b['name_lines'],name_size,style['speaker_color'],'speaker')
            continue
        name=b.get('speaker','') if style['show_speaker'] else ''
        size=max(8,round(style['font_size']*k*b.get('font_scale',1)))
        align=style['alignment'];anchor={'left':'nw','center':'n','right':'ne'}[align]
        x={'left':l+pad,'center':(l+r)/2,'right':r-pad}[align]
        tag=f'caption_text_{i}'
        while True:
            canvas.delete(tag)
            bodyfont=('Segoe UI',-size,'bold')
            namefont=('Segoe UI',-max(7,round(size*.7)),'bold')
            y=t+max(2,8*k)
            if name:
                item=canvas.create_text(x,y,anchor=anchor,text=name,font=namefont,
                    fill=style['speaker_color'],justify=align,width=available,tags=('caption',tag,'speaker'))
                bb=canvas.bbox(item);y=bb[3]+max(1,2*k)
            canvas.create_text(x,y,anchor=anchor,text=b['text'],font=bodyfont,fill='#FFFFFF',
                justify=align,width=available,tags=('caption',tag,'dialogue'))
            bb=canvas.bbox(tag)
            if size<=8 or bb[3]<=bottom-max(2,6*k):break
            size-=1
        # Canvas keeps font descriptors after local Python Font objects expire.
