"""Native, responsive control panel. All capture/model work stays in workers."""
import tkinter as tk
import customtkinter as ctk
from PIL import Image,ImageTk
from ediz_game_translator.storage.region_profiles import CROP_KEYS,game_names
from ediz_game_translator.storage.subtitle_styles import DEFAULT_STYLE,style_for,valid_style
from ediz_game_translator.subtitles.layout import arrange_blocks,contain
from ediz_game_translator.subtitles.canvas_view import draw_captions

BG='#080C15';CARD='#111827';SURFACE='#161F2F';INK='#EDF4FA';MUTED='#8F9CB0';ACCENT='#50E2BE';BORDER='#253044'
PAGES=('Canlı Çeviri','Altyazı Tasarımı','Oyun Profilleri','Bağlantılar','Tanılama')


class Combo(ctk.CTkComboBox):
    def __init__(self,*args,**kwargs):
        kwargs.setdefault('values',[])
        super().__init__(*args,**kwargs)
    def __setitem__(self,key,value):self.configure(**{key:value})
    def __getitem__(self,key):return self.cget(key)
    def current(self,index=None):
        values=self.cget('values')
        if index is not None:
            if values:self.set(values[index])
        else:return values.index(self.get()) if self.get() in values else -1


class Button(ctk.CTkButton):
    def __getitem__(self,key):return self.cget(key)


class ScrollPage:
    def __init__(self,parent):
        self.outer=ctk.CTkScrollableFrame(parent,fg_color=BG,corner_radius=0,
            scrollbar_button_color=BORDER,scrollbar_button_hover_color=MUTED)
        self.body=self.outer
        self.canvas=self.outer._parent_canvas


def build_ui(w):
    root=w.root;s=w.settings
    ctk.set_appearance_mode('dark')
    try:root.configure(fg_color=BG)
    except tk.TclError:root.configure(bg=BG)
    scale=root._get_window_scaling() if hasattr(root,'_get_window_scaling') else 1
    width=min(1220,int(root.winfo_screenwidth()/scale)-60)
    height=min(850,int(root.winfo_screenheight()/scale)-90)
    x=max(0,round((root.winfo_screenwidth()-width*scale)/2))
    y=max(0,round((root.winfo_screenheight()-height*scale-40)/2))
    root.geometry(f'{width}x{height}+{x}+{y}')
    root.minsize(820,520)
    sidebar=ctk.CTkFrame(root,width=205,fg_color='#0C1220',corner_radius=0)
    sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
    def label(parent,text='',size=14,color=INK,**kw):
        return ctk.CTkLabel(parent,text=text,font=('Segoe UI',size),text_color=color,anchor='w',**kw)
    label(sidebar,'EDIZ',30,ACCENT).pack(anchor='w',padx=24,pady=(29,0))
    label(sidebar,'GAME TRANSLATOR',11,MUTED).pack(anchor='w',padx=24,pady=(0,30))
    container=ctk.CTkFrame(root,fg_color=BG,corner_radius=0);container.pack(side='right',fill='both',expand=True)
    w.pages={name:ScrollPage(container) for name in PAGES};w.nav_buttons={};w.page_after=None
    def show(name):
        for page in w.pages.values():page.outer.pack_forget()
        w.pages[name].outer.pack(fill='both',expand=True,padx=17,pady=14);w.current_page=name
        for key,b in w.nav_buttons.items():b.configure(fg_color=SURFACE if key==name else 'transparent',text_color=ACCENT if key==name else MUTED)
    w.show_page=show
    for name in PAGES:
        b=Button(sidebar,text=name,anchor='w',height=44,font=('Segoe UI',14),corner_radius=10,
            fg_color='transparent',hover_color=SURFACE,text_color=MUTED,command=lambda n=name:show(n))
        b.pack(fill='x',padx=12,pady=4);w.nav_buttons[name]=b
    label(sidebar,'YEREL · ÖZEL · ÇEVRİMDIŞI',10,ACCENT).pack(side='bottom',padx=22,pady=(0,24))
    label(sidebar,'Canlı kaynak senkronizasyonu',10,MUTED).pack(side='bottom',padx=22,pady=(0,8))
    def button(parent,text,command,primary=False,**kw):
        return Button(parent,text=text,command=command,height=38,corner_radius=9,
            fg_color=ACCENT if primary else '#233047',hover_color='#7DEBD0' if primary else '#30425D',
            text_color=BG if primary else INK,font=('Segoe UI',13,'bold' if primary else 'normal'),**kw)
    def card(parent,title,sub=None):
        box=ctk.CTkFrame(parent,fg_color=CARD,corner_radius=14,border_width=1,border_color=BORDER)
        box.pack(fill='x',padx=6,pady=(0,14))
        inner=ctk.CTkFrame(box,fg_color='transparent');inner.pack(fill='both',expand=True,padx=20,pady=17)
        if title:label(inner,title,17).pack(fill='x',pady=(0,4))
        if sub:label(inner,sub,12,MUTED,wraplength=590,justify='left').pack(fill='x',pady=(0,11))
        return inner
    def row(parent):
        r=ctk.CTkFrame(parent,fg_color='transparent');r.pack(fill='x',pady=5);return r
    def entry(parent,title,var,secret=False):
        r=row(parent);r.grid_columnconfigure(1,weight=1)
        label(r,title,12,MUTED).grid(row=0,column=0,sticky='w',padx=(0,14))
        e=ctk.CTkEntry(r,textvariable=var,show='•' if secret else '',fg_color=SURFACE,border_color=BORDER,height=34)
        e.grid(row=0,column=1,sticky='ew');return e
    def combo(parent,title,var,values):
        r=row(parent);label(r,title,12,MUTED).pack(side='left',padx=(0,12))
        c=Combo(r,variable=var,values=values,state='readonly',fg_color=SURFACE,border_color=BORDER,button_color=BORDER,height=34)
        c.pack(side='right',fill='x',expand=True);return c
    def heading(name,sub):
        p=w.pages[name].body
        label(p,name,26).pack(fill='x',padx=8,pady=(5,2));label(p,sub,12,MUTED).pack(fill='x',padx=8,pady=(0,21));return p
    strings={'obs_port':'obs_port','source':'obs_source','game':'game','font_var':'font_size',
        'bottom_var':'overlay_bottom','interval':'scan_interval','capture_width':'capture_width',
        'ocr_profile':'ocr_profile','camera_config':'camera_config','local_engine':'translation_engine',
        'local_python':'local_python','local_model_path':'local_model_path','local_device':'local_device',
        'local_compute':'local_compute_type','local_workers':'local_workers','local_threads':'local_threads',
        'capture_schedule':'capture_schedule'}
    for attr,key in strings.items():setattr(w,attr,tk.StringVar(root,value=str(s[key])))
    w.obs_password=tk.StringVar(root,value=w._get_secret('obs_password'))
    w.show_desktop=tk.BooleanVar(root,value=s['show_desktop']);w.diagnostic_mode=tk.BooleanVar(root,value=False)
    w.diagnostic_logs=tk.BooleanVar(root,value=False);w.advanced_open=tk.BooleanVar(root,value=False)
    w.crop_vars={k:tk.StringVar(root,value=str(s[k])) for k in CROP_KEYS}
    for attr,value in {'connection_var':'OBS: Bekliyor   ·   Kamera: Kapalı   ·   Model: Yüklenmedi',
        'status_var':'Hazır. Bağlantılar başlatıldığında doğrulanır.','session_info_var':'Yalnız mevcut kaynak replikler gösterilir.',
        'last_source_var':'Henüz İngilizce replik algılanmadı.','last_translation_var':'Henüz Türkçe çeviri yok.',
        'engine_info_var':'Model yüklenmedi.','crop_summary':'Oyuna özel OCR alanı','monitor_var':''}.items():
        setattr(w,attr,tk.StringVar(root,value=value))
    w.metric_vars={key:tk.StringVar(root,value='—') for key in ('ocr','translation','capacity','renderer','active','removal')}
    home=heading(PAGES[0],'Oyununa odaklan. Diyalogları Türkçe takip et.')
    hero=card(home,'Oturum',None)
    r=row(hero);r.grid_columnconfigure(0,weight=1)
    w.game_combo=Combo(r,variable=w.game,values=game_names(s),state='readonly',height=40,
        fg_color=SURFACE,border_color=BORDER,button_color=BORDER)
    w.game_combo.grid(row=0,column=0,sticky='ew',padx=(0,12))
    w.start_btn=button(r,'▶  ÇEVİRİYİ BAŞLAT',w.toggle_translation,True,width=220)
    w.start_btn.grid(row=0,column=1)
    label(hero,textvariable=w.connection_var,size=12,color=MUTED,wraplength=660,justify='left').pack(fill='x',pady=(7,2))
    label(hero,textvariable=w.status_var,size=13,color=ACCENT,wraplength=660,justify='left').pack(fill='x',pady=(3,0))
    preview=card(home,'Canlı önizleme','Ham görüntü yalnız yakalama açıkken gelir. Maske yalnız gösterim katmanındadır.')
    w.live_canvas=tk.Canvas(preview,height=240,bg=BG,highlightthickness=0);w.live_canvas.pack(fill='x',pady=(7,9))
    metrics=row(preview)
    for key,title in [('ocr','OCR'),('translation','Yerel çeviri'),('active','Aktif replik')]:
        box=ctk.CTkFrame(metrics,fg_color=SURFACE,corner_radius=10);box.pack(side='left',fill='x',expand=True,padx=3)
        label(box,title,11,MUTED).pack(anchor='w',padx=12,pady=(8,0));label(box,textvariable=w.metric_vars[key],size=20,color=INK).pack(anchor='w',padx=12,pady=(0,8))
    label(preview,textvariable=w.session_info_var,size=11,color=MUTED,wraplength=660).pack(fill='x',pady=(5,0))
    last=card(home,'Son replik · oturum geçmişi')
    for prefix,var,color in [('EN',w.last_source_var,MUTED),('TR',w.last_translation_var,INK)]:
        label(last,prefix,11,ACCENT).pack(anchor='w',pady=(4,0))
        label(last,textvariable=var,size=14,color=color,wraplength=660,justify='left').pack(fill='x',pady=(2,7))
    design=heading(PAGES[1],'Siyah zemin, beyaz diyalog ve oyuna özel maske.')
    example=card(design,'Görsel önizleme · örnek içerik','Bu görüntü bir bağlantı veya gerçek oyun ölçümü değildir.')
    w.style_canvas=tk.Canvas(example,height=235,bg=BG,highlightthickness=0);w.style_canvas.pack(fill='x',pady=6)
    opts=card(design,'Seçili oyunun altyazı görünümü')
    w.speaker_color=tk.StringVar(root,value=DEFAULT_STYLE['speaker_color']);w.show_speaker=tk.BooleanVar(root,value=True)
    w.alignment=tk.StringVar(root,value='center');w.mask_position=tk.StringVar(root,value='auto')
    w.mask_vars={k:tk.DoubleVar(root,value=v) for k,v in zip(('left','top','width','height'),(.11,.78,.78,.16))}
    w.style_value=tk.StringVar(root,value='36 px')
    r=row(opts);label(r,'Yazı boyutu',12,MUTED).pack(side='left');label(r,textvariable=w.style_value,size=12,color=ACCENT).pack(side='right')
    w.font_slider=ctk.CTkSlider(opts,from_=12,to=96,number_of_steps=84,progress_color=ACCENT,button_color=ACCENT,
        command=lambda value:(w.font_var.set(str(round(value))),w.style_value.set(f'{round(value)} px'),w.refresh_design()))
    w.font_slider.pack(fill='x',pady=8)
    combo(opts,'Karakter ismi rengi',w.speaker_color,['#50E2BE','#80A7FF','#FFD166','#FFFFFF'])
    ctk.CTkCheckBox(opts,text='Karakter ismini ayrı renkte göster',variable=w.show_speaker,command=lambda:w.refresh_design(),
        fg_color=ACCENT,text_color=INK,checkmark_color=BG).pack(anchor='w',pady=9)
    combo(opts,'Hizalama',w.alignment,['left','center','right'])
    combo(opts,'Yerleşim',w.mask_position,['auto','fixed'])
    label(opts,'auto: güvenilir OCR kutusu · fixed: aşağıdaki oyun maskesi',11,MUTED).pack(anchor='w',pady=5)
    for key,title in [('left','Sol'),('top','Üst'),('width','Genişlik'),('height','Yükseklik')]:
        r=row(opts);label(r,title,12,MUTED,width=90).pack(side='left')
        slider=ctk.CTkSlider(r,from_=0 if key in ('left','top') else .03,to=1,variable=w.mask_vars[key],
            progress_color=ACCENT,button_color=ACCENT,command=lambda _:w.refresh_design())
        slider.pack(side='left',fill='x',expand=True,padx=8)
    r=row(opts);button(r,'Oyuna kaydet',w.save_subtitle_style,True).pack(side='left')
    button(r,'Önizlemeyi sıfırla',w.reset_subtitle_style).pack(side='left',padx=10)
    profiles=heading(PAGES[2],'OCR alanı ve siyah maske her oyun için ayrı saklanır.')
    profile=card(profiles,'Profil yönetimi')
    combo(profile,'Seçili oyun',w.game,game_names(s))
    r=row(profile);button(r,'+ Yeni oyun',w.add_game).pack(side='left');button(r,'Adını değiştir',w.rename_game).pack(side='left',padx=10)
    w.profile_cards=ctk.CTkFrame(profiles,fg_color='transparent');w.profile_cards.pack(fill='x')
    def refresh_profiles():
        for child in w.profile_cards.winfo_children():child.destroy()
        for name in game_names(w.settings):
            box=card(w.profile_cards,name,'Ayrı OCR bölgesi · ayrı altyazı maskesi')
            button(box,'Profili seç',lambda n=name:w.game.set(n)).pack(anchor='w')
    w.refresh_profiles=refresh_profiles
    region=card(profiles,'OCR bölgesi','Ham İngilizce görüntüden okunur; Türkçe maske OCR girdisine eklenmez.')
    w.region_canvas=tk.Canvas(region,width=160,height=90,bg=BG,highlightthickness=0);w.region_canvas.pack(anchor='w',pady=7)
    label(region,textvariable=w.crop_summary,size=12,color=MUTED).pack(anchor='w')
    button(region,'OCR bölgesini düzenle…',w.open_region_editor).pack(anchor='w',pady=10)
    connection=heading(PAGES[3],'PS5 → capture card → filtresiz OBS kaynağı → yerel OCR ve çeviri.')
    inputs=card(connection,'OBS ve ham capture card','Sanal Kamera: Output Type = Source; yalnız filtresiz capture card girdisi seçilmeli.')
    entry(inputs,'WebSocket portu',w.obs_port);entry(inputs,'OBS parolası',w.obs_password,True)
    w.source_combo=combo(inputs,'Ham kaynak',w.source,[])
    button(inputs,'Bağlantıyı test et / kaynakları getir',w.load_sources).pack(anchor='w',pady=7)
    entry(inputs,'OBS koleksiyon JSON',w.camera_config);button(inputs,'Koleksiyon dosyasını seç…',w._choose_camera_config).pack(anchor='w',pady=7)
    model=card(connection,'Yerel çeviri motoru','Model ayrı süreçte sıcak tutulur. Otomatik indirme ve ücretli servis geçişi yoktur.')
    entry(model,'Motor Python.exe',w.local_python);entry(model,'Model klasörü',w.local_model_path)
    button(model,'Model klasörünü seç…',w._choose_local_model).pack(anchor='w',pady=7)
    combo(model,'Motor',w.local_engine,['ct2-marian','argos-ct2']);combo(model,'Aygıt',w.local_device,['cpu','cuda'])
    combo(model,'Hesaplama',w.local_compute,['int8','int8_float16','float32'])
    label(model,textvariable=w.engine_info_var,size=12,color=ACCENT,wraplength=620).pack(fill='x',pady=8)
    output=card(connection,'Gösterim çıkışları','HDMI passthrough üzerine yazılımla çizim yapılamaz. OBS veya Windows overlay kullanılır.')
    label(output,'http://127.0.0.1:8788/overlay',13,ACCENT).pack(anchor='w',pady=5)
    button(output,'OBS altyazı katmanını aç',w.open_overlay).pack(anchor='w',pady=5)
    ctk.CTkCheckBox(output,text='Windows monitöründe de göster',variable=w.show_desktop,fg_color=ACCENT,
        checkmark_color=BG).pack(anchor='w',pady=9)
    w.monitor_combo=combo(output,'Monitör',w.monitor_var,[])
    advanced=card(connection,'Gelişmiş ayarlar')
    details=ctk.CTkFrame(advanced,fg_color='transparent')
    ctk.CTkCheckBox(advanced,text='Teknik seçenekleri göster',variable=w.advanced_open,fg_color=ACCENT,checkmark_color=BG,
        command=lambda:details.pack(fill='x',pady=10) if w.advanced_open.get() else details.pack_forget()).pack(anchor='w',pady=6)
    entry(details,'Eşzamanlı işçi (GPU 1)',w.local_workers);entry(details,'CPU iş parçacığı',w.local_threads)
    entry(details,'OCR aralığı (sn)',w.interval);combo(details,'OCR planı',w.capture_schedule,['fixed_fast','adaptive'])
    label(details,'Mevcut oyun notları / bağlam',12,MUTED).pack(anchor='w',pady=(10,4))
    w.lore_text=tk.Text(details,height=3,bg=SURFACE,fg=INK,insertbackground=INK,relief='flat',wrap='word',font=('Segoe UI',10))
    w.lore_text.pack(fill='x');w.lore_text.insert('1.0',s['lore'])
    button(connection,'Bağlantı ayarlarını kaydet',w.save_preferences,True).pack(fill='x',padx=6,pady=(0,18))
    diagnostics=heading(PAGES[4],'Ölçülmeyen değerler — olarak gösterilir. Süreler aynı makinenin monoton saatindendir.')
    stats=card(diagnostics,'Canlı ölçümler')
    for key,title in [('ocr','OCR'),('translation','Yerel model / son iş'),('capacity','İşlem kapasitesi beklemesi'),
        ('renderer','Renderer gönderim → ACK'),('active','Aktif kaynak replik'),('removal','Kaynak kaybı → kaldırma ACK')]:
        r=row(stats);label(r,title,12,MUTED).pack(side='left');label(r,textvariable=w.metric_vars[key],size=16,color=INK).pack(side='right')
    checks=card(diagnostics,'Test ve kayıtlar','Ayrıntılı günlük özel OCR metni içerebilir; varsayılan kapalıdır.')
    for title,var in [('Yalnız OCR tanılama modu',w.diagnostic_mode),('Ayrıntılı yerel günlük',w.diagnostic_logs)]:
        ctk.CTkCheckBox(checks,text=title,variable=var,fg_color=ACCENT,checkmark_color=BG).pack(anchor='w',pady=6)
    r=row(checks)
    for title,cmd in [('OCR testi',w.test_ocr),('Yerel test',w.test_ai),('Örnek altyazı',w.demo)]:button(r,title,cmd,width=130).pack(side='left',padx=(0,7))
    button(checks,'SRT dışa aktar',w.export_srt).pack(anchor='w',pady=10)
    journal=card(diagnostics,'Uygulama günlüğü')
    w.log_box=tk.Text(journal,height=10,bg=BG,fg=MUTED,wrap='word',state='disabled',font=('Consolas',10),relief='flat')
    w.log_box.pack(fill='both',expand=True,pady=5)
    def get_style():
        l=min(.97,max(0,w.mask_vars['left'].get()));t=min(.97,max(0,w.mask_vars['top'].get()))
        width=max(.03,min(1-l,w.mask_vars['width'].get()));height=max(.03,min(1-t,w.mask_vars['height'].get()))
        return valid_style(dict(font_size=int(w.font_var.get()),speaker_color=w.speaker_color.get(),
            show_speaker=bool(w.show_speaker.get()),alignment=w.alignment.get(),position=w.mask_position.get(),mask_rect=[l,t,l+width,t+height]))
    w.subtitle_style_from_ui=get_style
    def refresh_design(*_):
        try:style=get_style()
        except (ValueError,tk.TclError):return
        c=w.style_canvas;c.delete('all');cw=max(c.winfo_width(),400);ch=c.winfo_height()
        c.create_rectangle(0,0,cw,ch,fill='#101D2A',outline='')
        c.create_polygon(0,ch*.6,cw*.25,ch*.3,cw*.45,ch*.7,cw*.75,ch*.25,cw,ch*.5,cw,ch,0,ch,fill='#203448',outline='')
        c.create_text(16,14,text='ÖRNEK SAHNE · gerçek oyun kaydı değildir',anchor='nw',fill=MUTED,font=('Segoe UI',9))
        # Draw the English source underneath, so mask coverage is inspectable.
        rect=style['mask_rect'];x,y,fw,fh=contain(cw,ch)
        c.create_text(x+(rect[0]+rect[2])/2*fw,y+(rect[1]+rect[3])/2*fh,text='Scout: We should leave before they arrive.',fill='#C4CDD8',width=max(50,(rect[2]-rect[0])*fw-10),font=('Segoe UI',10))
        sample=[dict(id=0,text='Onlar gelmeden buradan ayrılmalıyız.',speaker='Scout',source_size=[1920,1080])]
        draw_captions(c,arrange_blocks(sample,style),style,cw,ch)
    w.refresh_design=refresh_design
    def load_style():
        style=style_for(w.settings,w.game.get());w.font_var.set(str(style['font_size']));w.font_slider.set(style['font_size'])
        w.style_value.set(f"{style['font_size']} px");w.speaker_color.set(style['speaker_color']);w.show_speaker.set(style['show_speaker'])
        w.alignment.set(style['alignment']);w.mask_position.set(style['position'])
        l,t,r,b=style['mask_rect']
        for key,value in zip(w.mask_vars,(l,t,r-l,b-t)):w.mask_vars[key].set(value)
        refresh_design()
    w.load_subtitle_style=load_style
    for var in (w.speaker_color,w.alignment,w.mask_position):var.trace_add('write',refresh_design)
    w.style_canvas.bind('<Configure>',refresh_design)
    w.preview_image=None;w.last_preview_sequence=None;w.next_preview=0
    def refresh_live(state):
        c=w.live_canvas;cw=c.winfo_width();ch=c.winfo_height();packet,status=w._preview_packet()
        c.delete('all')
        if packet is not None:
            im=packet.image.copy();im.thumbnail((max(1,cw),max(1,ch)),Image.Resampling.BILINEAR)
            w.preview_image=ImageTk.PhotoImage(im,master=root);c.create_image(cw/2,ch/2,image=w.preview_image)
        else:c.create_text(cw/2,ch/2,text='Ham görüntü bekleniyor' if w.running else 'Çeviriyi başlattığında oyun burada görünür.',fill=MUTED,font=('Segoe UI',11),width=max(100,cw-40))
        if packet is not None:draw_captions(c,state['blocks'],state['style'],cw,ch)
    w.refresh_live_preview=refresh_live
    load_style();refresh_profiles();show(PAGES[0])
