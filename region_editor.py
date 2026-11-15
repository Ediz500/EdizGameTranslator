"""Tk ROI editor: shared latest frame, normalized draft, API-free OCR test."""
import queue
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image,ImageEnhance,ImageTk
from region_geometry import RegionDraft,Viewport,handle_points,hit_test,drag

BG='#101923'
PANEL='#172432'
INK='#e6edf5'
ACCENT='#53c6e7'


def ocr_on_region(image,rect,engine):
    """Crop exactly like obs_capture.crop_frame; return full-image pixel boxes."""
    w,h=image.size
    percentages=tuple(v*100 for v in rect)
    l,t,r,b=(int(s*v/100) for v,s in zip(percentages,(w,h,w,h)))
    result=engine(image.crop((l,t,r,b)))
    texts=[str(x) for x in (getattr(result,'txts',None) or [])]
    scores=[float(x) for x in (getattr(result,'scores',None) or [])]
    boxes=getattr(result,'boxes',None)
    full_boxes=[]
    if boxes is not None:
        for box in boxes:
            full_boxes.append([(float(x)+l,float(y)+t) for x,y in box])
    return dict(texts=texts,scores=scores,boxes=full_boxes)


class RegionEditor:
    def __init__(self,parent,game,rect,provider,ocr_provider,spawn,on_save,on_close):
        self.window=tk.Toplevel(parent)
        self.window.title('OCR Bölgesi Düzenleyici · '+game)
        self.window.geometry('1040x780')
        self.window.minsize(760,600)
        self.window.configure(bg=BG)
        self.window.transient(parent)
        self.provider,self.ocr_provider,self.spawn=provider,ocr_provider,spawn
        self.on_save,self.on_close=on_save,on_close
        self.draft=RegionDraft(rect)
        self.packet=None
        self.paused=False
        self.closed=False
        self.generation=0
        self.result=None
        self.in_test=False
        self.results=queue.Queue()
        self.view=None
        self.gesture=None
        self.photo=None
        self.base_key=None
        self.base=None
        self.next_preview=0
        self._make_ui(game)
        self.window.protocol('WM_DELETE_WINDOW',self.cancel)
        self.window.bind('<Escape>',lambda _:self.cancel())
        self.after_id=self.window.after(0,self._tick)

    def _make_ui(self,game):
        style=ttk.Style(self.window)
        style.theme_use('clam')
        style.configure('Region.TFrame',background=BG)
        style.configure('Region.TLabel',background=BG,foreground=INK,font=('Segoe UI',10))
        style.configure('Region.TButton',background='#26394a',foreground=INK,borderwidth=0,
                        font=('Segoe UI',10),padding=(12,8))
        style.map('Region.TButton',background=[('active','#315069'),('disabled',PANEL)],foreground=[('disabled','#718599')])
        style.configure('Region.Primary.TButton',background=ACCENT,foreground=BG,borderwidth=0,
                        font=('Segoe UI',10),padding=(12,8))
        style.map('Region.Primary.TButton',background=[('active','#7ad7ed')])
        header=tk.Frame(self.window,bg=BG,padx=18,pady=12)
        header.pack(fill='x')
        tk.Label(header,text='OCR BÖLGESİ',bg=BG,fg=ACCENT,font=('Segoe UI',17,'bold')).pack(anchor='w')
        tk.Label(header,text=f'Profil: {game}   ·   Alanı taşı veya sekiz tutamaçtan boyutlandır.',
                 bg=BG,fg=INK,font=('Segoe UI',10)).pack(anchor='w',pady=(3,0))
        toolbar=tk.Frame(self.window,bg=BG,padx=18)
        toolbar.pack(fill='x',pady=(0,8))
        self.pause_btn=ttk.Button(toolbar,text='Ⅱ Önizlemeyi duraklat',command=self.toggle_pause,style='Region.TButton')
        self.pause_btn.pack(side='left')
        self.test_btn=ttk.Button(toolbar,text='OCR test et · API yok',command=self.test_ocr,style='Region.TButton')
        self.test_btn.pack(side='left',padx=8)
        self.feed_label=tk.Label(toolbar,text='Kare bekleniyor…',bg=BG,fg='#9fb3c8',font=('Segoe UI',9))
        self.feed_label.pack(side='right')
        self.canvas=tk.Canvas(self.window,bg='#080e15',highlightthickness=0,cursor='arrow')
        self.canvas.pack(fill='both',expand=True,padx=18)
        self.canvas.bind('<Configure>',lambda _:self._draw())
        self.canvas.bind('<ButtonPress-1>',self._press)
        self.canvas.bind('<B1-Motion>',self._motion)
        self.canvas.bind('<ButtonRelease-1>',self._release)
        self.canvas.bind('<Motion>',self._hover)
        self.coordinates=tk.StringVar()
        tk.Label(self.window,textvariable=self.coordinates,bg=BG,fg=ACCENT,font=('Segoe UI',10)).pack(anchor='w',padx=18,pady=(8,2))
        self.status=tk.StringVar(value='Önizleme hedefi 1–2 FPS. Fareyle düzenleme görüntüyü dondurur.')
        tk.Label(self.window,textvariable=self.status,bg=BG,fg=INK,anchor='w',wraplength=960).pack(fill='x',padx=18)
        self.text=tk.Text(self.window,height=4,bg=PANEL,fg=INK,font=('Segoe UI',10),wrap='word',relief='flat',state='disabled')
        self.text.pack(fill='x',padx=18,pady=8)
        self._text('OCR testi bu penceredeki kareyi kullanır. Ekran görüntüsü veya API isteği oluşturmaz.')
        footer=tk.Frame(self.window,bg=BG,padx=18,pady=10)
        footer.pack(fill='x')
        ttk.Button(footer,text='Sıfırla',command=self.reset,style='Region.TButton').pack(side='left')
        self.undo_btn=ttk.Button(footer,text='Geri al',command=self.undo,style='Region.TButton')
        self.undo_btn.pack(side='left',padx=8)
        ttk.Button(footer,text='Kaydet',command=self.save,style='Region.Primary.TButton').pack(side='right')
        ttk.Button(footer,text='İptal',command=self.cancel,style='Region.TButton').pack(side='right',padx=8)
        self._coordinate_label()

    def _text(self,text):
        self.text.configure(state='normal');self.text.delete('1.0','end')
        self.text.insert('1.0',text);self.text.configure(state='disabled')

    def _coordinate_label(self):
        l,t,r,b=self.draft.rect
        self.coordinates.set(f'Sol %{l*100:.2f}   Üst %{t*100:.2f}   Sağ %{r*100:.2f}   Alt %{b*100:.2f}')
        self.undo_btn.configure(state='normal' if self.draft.history else 'disabled')

    def _tick(self):
        if self.closed:return
        now=time.monotonic()
        if not self.paused and now>=self.next_preview:
            self.next_preview=now+.6
            packet,status=self.provider()
            self.feed_label.configure(text=status)
            if packet is not None and packet is not self.packet:
                self.packet=packet;self._invalidate();self._draw()
        try:
            while True:
                token,result,error=self.results.get_nowait()
                self.in_test=False
                self.test_btn.configure(state='normal')
                if token!=self.generation:
                    self.status.set('Görüntü veya alan değişti; eski OCR sonucu kullanılmadı.')
                    continue
                if error:
                    self.status.set('OCR testi başarısız: '+error)
                else:
                    self.result=result
                    lines=[f'{i+1}. {text}'+(f"  [{result['scores'][i]:.2f}]" if i<len(result['scores']) else '')
                           for i,text in enumerate(result['texts'])]
                    self._text('\n'.join(lines) or 'Bu alanda metin bulunamadı.')
                    self.status.set('OCR testi tamamlandı. Sarı kutular algılanan yazıları gösterir; API kullanılmadı.')
                    self._draw()
        except queue.Empty:pass
        self.after_id=self.window.after(80,self._tick)

    def _invalidate(self):
        self.generation+=1
        if self.result is not None:self._text('Görüntü veya alan değişti; yeni OCR testi yap.')
        self.result=None

    def _draw(self):
        if self.closed:return
        self.canvas.delete('all')
        self._coordinate_label()
        cw,ch=self.canvas.winfo_width(),self.canvas.winfo_height()
        if self.packet is None or min(cw,ch)<2:
            self.canvas.create_text(max(1,cw)/2,max(1,ch)/2,text='Ham oyun görüntüsü bekleniyor…',fill='#9fb3c8',font=('Segoe UI',13))
            return
        image=self.packet.image
        fitted=Viewport.fit(max(1,cw-16),max(1,ch-16),*image.size)
        self.view=Viewport(fitted.x+8,fitted.y+8,fitted.width,fitted.height)
        view=self.view
        size=(max(1,round(view.width)),max(1,round(view.height)))
        key=(id(self.packet),size)
        if key!=self.base_key:
            self.base=image.resize(size,Image.Resampling.BILINEAR)
            self.dimmed=ImageEnhance.Brightness(self.base).enhance(.55)
            self.base_key=key
        rendered=self.dimmed.copy()
        l,t,r,b=self.draft.rect
        pixels=(round(l*size[0]),round(t*size[1]),round(r*size[0]),round(b*size[1]))
        rendered.paste(self.base.crop(pixels),pixels)
        self.photo=ImageTk.PhotoImage(rendered,master=self.window)
        self.canvas.create_image(view.x,view.y,image=self.photo,anchor='nw')
        self.canvas.create_rectangle(*view.rect(self.draft.rect),outline=ACCENT,width=2,tags='roi')
        if self.result:
            for i,box in enumerate(self.result['boxes']):
                points=[view.point(x/image.width,y/image.height) for x,y in box]
                self.canvas.create_polygon(*[v for point in points for v in point],fill='',outline='#ffd166',width=2,tags='ocr_box')
                if points:self.canvas.create_text(*points[0],text=str(i+1),anchor='sw',fill='#ffd166')
        for name,point in handle_points(self.draft.rect).items():
            x,y=view.point(*point)
            self.canvas.create_rectangle(x-4,y-4,x+4,y+4,fill=INK,outline=ACCENT,width=2,tags=('handle',name))

    def _set_pause(self,paused):
        self.paused=paused
        self.pause_btn.configure(text='▶ Önizlemeye devam et' if paused else 'Ⅱ Önizlemeyi duraklat')
        if paused:self.feed_label.configure(text='Duraklatıldı · yakalama işçisi çalışmaya devam eder')
        else:self.next_preview=0

    def toggle_pause(self):
        self._set_pause(not self.paused)
        if not self.paused:self._invalidate();self._draw()

    def _press(self,event):
        if self.view is None or self.packet is None:return
        mode=hit_test(self.view,self.draft.rect,event.x,event.y)
        if mode:
            self._set_pause(True)
            self.gesture=(mode,self.view.inverse(event.x,event.y),self.draft.rect)

    def _motion(self,event):
        if not self.gesture:return
        mode,(x0,y0),rect=self.gesture
        x,y=self.view.inverse(event.x,event.y)
        self.draft.rect=drag(rect,mode,x-x0,y-y0)
        self._invalidate();self._draw()

    def _release(self,event):
        if self.gesture:
            original=self.gesture[2]
            if original!=self.draft.rect:
                self.draft.history.append(original);self.draft.history=self.draft.history[-50:]
            self.gesture=None;self._draw()

    def _hover(self,event):
        if self.view is None:return
        mode=hit_test(self.view,self.draft.rect,event.x,event.y)
        cursors={'move':'fleur','n':'sb_v_double_arrow','s':'sb_v_double_arrow','e':'sb_h_double_arrow',
                 'w':'sb_h_double_arrow','nw':'top_left_corner','ne':'top_right_corner',
                 'sw':'bottom_left_corner','se':'bottom_right_corner'}
        self.canvas.configure(cursor=cursors.get(mode,'arrow'))

    def reset(self):
        self.draft.reset();self._invalidate();self._draw()

    def undo(self):
        self.draft.undo();self._invalidate();self._draw()

    def test_ocr(self):
        if self.in_test or self.packet is None:return
        engine=self.ocr_provider()
        if engine is None:
            self.status.set('OCR işçisi hazırlanıyor; kare geldiğinde tekrar dene.');return
        self._set_pause(True)
        self.result=None;self._draw()
        self._text('Seçili alan okunuyor…')
        token=self.generation;image=self.packet.image;rect=self.draft.rect
        self.in_test=True;self.test_btn.configure(state='disabled')
        self.status.set('Seçili alan yerel OCR ile okunuyor…')
        def work():
            try:self.results.put((token,ocr_on_region(image,rect,engine),None))
            except Exception as exc:self.results.put((token,None,type(exc).__name__))
        self.spawn(work)

    def save(self):
        try:self.on_save(self.draft.rect)
        except Exception as exc:
            self.status.set('Kaydedilemedi: '+str(exc));return
        self.close()

    def cancel(self):
        self.close()

    def close(self):
        if self.closed:return
        self.closed=True;self.generation+=1
        self.window.after_cancel(self.after_id)
        self.window.destroy()
        self.photo=None;self.packet=None;self.base=None
        self.on_close()
