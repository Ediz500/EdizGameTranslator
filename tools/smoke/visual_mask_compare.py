"""Deterministic synthetic masks; no game capture or private dialogue."""
from pathlib import Path
from PIL import Image,ImageDraw
from ediz_game_translator.subtitles.layout import _fixed_layout,arrange_blocks,_font,_wrap
from ediz_game_translator.storage.subtitle_styles import DEFAULT_STYLE


def main():
    output=Path(__file__).resolve().parents[2]/'docs/images/visual-mask-comparison.png'
    output.parent.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGB',(1920,1800),'#080C15');draw=ImageDraw.Draw(image)
    cases=[('Kısa İngilizce / kısa Türkçe','Wait here.','Burada bekle.',[.42,.77,.58,.83]),
        ('Uzun İngilizce / kısa Türkçe','We must return to the station before nightfall.','Hava kararmadan dönmeliyiz.',[.18,.77,.82,.84]),
        ('Kısa İngilizce / uzun Türkçe','Come with me.','Birlikte yola çıkmalıyız. Köprüye ulaşmadan önce sessiz kalıp çevredeki devriyeleri dikkatle izlememiz gerekiyor. Kimseyi geride bırakmayacağız.',[.41,.77,.59,.83])]
    def text_at(x,y,text,size,color='#EDF4FA'):draw.text((x,y),text,font=_font(size),fill=color)
    def lines_at(rect,lines,size,color,ox,oy):
        font=_font(max(1,round(size*.5)))
        for i,line in enumerate(lines):
            x=ox+(rect[0]+rect[2])/2*960-font.getlength(line)/2
            draw.text((x,oy+rect[1]*540+i*size*1.28*.5),line,font=font,fill=color,anchor='lt')
    for row,(title,english,turkish,bounds) in enumerate(cases):
        oy=row*600+60;text_at(24,row*600+16,title+' · SENTETİK, gerçek oyun kaydı değildir',24)
        b=dict(id=1,subtitle_id=1,text=turkish,speaker='Scout',bounds=bounds,source_size=[960,540])
        before=_fixed_layout([b],DEFAULT_STYLE)[0];after=arrange_blocks([b],DEFAULT_STYLE)[0]
        for col,block in enumerate((before,after)):
            ox=col*960;draw.rectangle((ox,oy,ox+959,oy+539),fill='#152536')
            draw.polygon([(ox,oy+370),(ox+250,oy+160),(ox+450,oy+370),(ox+760,oy+100),(ox+959,oy+370),(ox+959,oy+539),(ox,oy+539)],fill='#243B50')
            text_at(ox+25,oy+20,'ÖNCE · genişlik alt sınırı' if col==0 else 'SONRA · dinamik maske',22,'#8F9CB0')
            font=_font(20);width=font.getlength(english)
            draw.text((ox+(bounds[0]+bounds[2])/2*960-width/2,oy+bounds[1]*540),english,font=font,fill='white',anchor='lt')
            r=block['mask_rect'];draw.rectangle((ox+r[0]*960,oy+r[1]*540,ox+r[2]*960,oy+r[3]*540),fill='#000000')
            if 'body_rect' in block:
                lines_at(block['body_rect'],block['display_lines'],block['visual_font_size'],'#FFFFFF',ox,oy)
                lines_at(block['name_rect'],block['name_lines'],max(6,round(block['visual_font_size']*.7)),'#50E2BE',ox,oy)
            else:
                lines=_wrap(turkish,_font(36),(r[2]-r[0])*1920-36)
                bottom=(r[1]+r[3])/2+(len(lines)*36*1.28+32)/2160
                body=[r[0]+18/1920,bottom-len(lines)*36*1.28/1080,r[2]-18/1920,bottom]
                name=[body[0],body[1]-32/1080,body[2],body[1]]
                lines_at(body,lines,36,'#FFFFFF',ox,oy);lines_at(name,['Scout'],25,'#50E2BE',ox,oy)
            text_at(ox+25,oy+500,f"Maske genişliği: %{(r[2]-r[0])*100:.1f}",20,'#50E2BE')
    image.save(output);print(output.relative_to(Path(__file__).resolve().parents[2]).as_posix())


if __name__=='__main__':main()
