"""Two-page Tk view. Capture, accounting and session ownership stay in app.py."""
import tkinter as tk
from tkinter import ttk
from core import PRICE_PER_MILLION
from region_profiles import CROP_KEYS,game_names

BG='#0e1621';CARD='#172333';INK='#edf3fa';MUTED='#9cacc0';ACCENT='#64d8c0'


class ScrollPage:
    def __init__(self,parent):
        self.outer=ttk.Frame(parent)
        self.canvas=tk.Canvas(self.outer,bg=BG,highlightthickness=0)
        bar=ttk.Scrollbar(self.outer,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');self.canvas.pack(fill='both',expand=True)
        self.body=ttk.Frame(self.canvas,padding=(24,18))
        item=self.canvas.create_window(0,0,window=self.body,anchor='nw')
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(item,width=e.width))
        self.body.bind('<Configure>',lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        # Scope wheel handling to the active page; do not bind_all across dialogs.
        def wheel(e):
            self.canvas.yview_scroll(-int(e.delta/120),'units')
            return 'break'
        self.wheel=wheel

    def bind_wheel(self):
        def walk(widget):
            if not isinstance(widget,(tk.Text,ttk.Combobox)):
                widget.bind('<MouseWheel>',self.wheel,add='+')
            for child in widget.winfo_children():walk(child)
        walk(self.outer)


def build_ui(w):
    root=w.root;s=w.settings
    style=ttk.Style(root);style.theme_use('clam')
    for name,bg in [('TFrame',BG),('Card.TFrame',CARD),('TLabel',BG),('Card.TLabel',CARD)]:
        style.configure(name,background=bg,foreground=INK,font=('Segoe UI',10))
    style.configure('TButton',font=('Segoe UI',10),padding=(12,8),background='#26394d',foreground=INK,borderwidth=0)
    style.map('TButton',background=[('active','#34516b')],foreground=[('disabled','#718399')])
    style.configure('Primary.TButton',font=('Segoe UI',13,'bold'),padding=(18,15),background=ACCENT,foreground=BG)
    style.map('Primary.TButton',background=[('active','#86e6d2')])
    style.configure('Nav.TButton',anchor='w',padding=(18,13))
    style.configure('TCheckbutton',background=CARD,foreground=INK,font=('Segoe UI',10),padding=4)
    style.map('TCheckbutton',background=[('active',CARD)])
    style.configure('TEntry',padding=6,fieldbackground='#223246',foreground=INK)
    style.configure('TCombobox',padding=6,fieldbackground='#223246',foreground=INK)
    for name in ('TEntry','TCombobox'):
        style.configure(name,bordercolor='#34516b',lightcolor='#34516b',darkcolor='#34516b')
    style.configure('Vertical.TScrollbar',background='#26394d',troughcolor=BG,bordercolor=BG,arrowcolor=MUTED)
    style.map('TCombobox',fieldbackground=[('readonly','#223246')],foreground=[('readonly',INK)])
    root.configure(bg=BG)
    root.geometry('1120x820');root.minsize(900,650)
    sidebar=tk.Frame(root,bg='#111d2b',width=194,padx=14,pady=24)
    sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
    tk.Label(sidebar,text='EDIZ',bg='#111d2b',fg=ACCENT,font=('Segoe UI',23,'bold')).pack(anchor='w',padx=12)
    tk.Label(sidebar,text='GAME TRANSLATOR',bg='#111d2b',fg=MUTED,font=('Segoe UI',9)).pack(anchor='w',padx=12,pady=(0,30))
    container=ttk.Frame(root);container.pack(side='right',fill='both',expand=True)
    pages={name:ScrollPage(container) for name in ('Ana Sayfa','Ayarlar')}
    w.pages=pages;w.current_page='Ana Sayfa'
    nav={}
    def show_page(name):
        for page in pages.values():page.outer.pack_forget()
        pages[name].outer.pack(fill='both',expand=True);w.current_page=name
        if getattr(w,'page_after',None) is not None:root.after_cancel(w.page_after)
        def position():
            w.page_after=None;pages[name].canvas.yview_moveto(0)
        w.page_after=root.after_idle(position)
        for key,button in nav.items():button.configure(text=('●  ' if key==name else '    ')+key)
    w.show_page=show_page
    for name in pages:
        nav[name]=ttk.Button(sidebar,text=name,style='Nav.TButton',command=lambda n=name:show_page(n))
        nav[name].pack(fill='x',pady=4)
    tk.Label(sidebar,text='v0.1  ·  Windows\nHam oyun → Türkçe',bg='#111d2b',fg=MUTED,
             justify='left',font=('Segoe UI',9)).pack(side='bottom',anchor='w',padx=12)
    w.nav_buttons=nav
    def label(parent,text,size=10,color=INK):
        return tk.Label(parent,text=text,bg=parent.cget('background'),fg=color,font=('Segoe UI',size),anchor='w')
    def card(page,title,sub=None):
        box=tk.Frame(page,bg=CARD,padx=20,pady=16);box.pack(fill='x',pady=(0,14))
        label(box,title,13).pack(fill='x')
        if sub:label(box,sub,9,MUTED).pack(fill='x',pady=(3,10))
        return box
    def row(box):
        r=tk.Frame(box,bg=CARD);r.pack(fill='x',pady=5);return r
    def field(box,title,var,width=22,secret=False):
        r=row(box);label(r,title).pack(side='left')
        entry=ttk.Entry(r,textvariable=var,width=width,show='•' if secret else '')
        entry.pack(side='right',fill='x',expand=True,padx=(18,0));return entry
    # The controller keeps typed variables for config compatibility. Technical
    # controls live only in Settings, some behind the advanced disclosure.
    strings={'obs_port':'obs_port','source':'obs_source','model':'model','game':'game','budget':'budget_try',
             'usd_try':'usd_try','font_var':'font_size','bottom_var':'overlay_bottom','interval':'scan_interval',
             'capture_width':'capture_width','ocr_profile':'ocr_profile','camera_config':'camera_config'}
    for attr,key in strings.items():setattr(w,attr,tk.StringVar(value=str(s[key])))
    w.obs_password=tk.StringVar(value=w._get_secret('obs_password'))
    w.api_key=tk.StringVar(value='')  # Historical key stays untouched in the OS vault.
    w.local_engine=tk.StringVar(value=s['translation_engine'])
    w.local_python=tk.StringVar(value=s['local_python'])
    w.local_model_path=tk.StringVar(value=s['local_model_path'])
    w.local_device=tk.StringVar(value=s['local_device'])
    w.local_compute=tk.StringVar(value=s['local_compute_type'])
    w.local_workers=tk.StringVar(value=str(s['local_workers']))
    w.local_threads=tk.StringVar(value=str(s['local_threads']))
    w.capture_schedule=tk.StringVar(value=s['capture_schedule'])
    w.show_desktop=tk.BooleanVar(value=s['show_desktop'])
    w.diagnostic_mode=tk.BooleanVar(value=False);w.diagnostic_logs=tk.BooleanVar(value=False)
    w.crop_vars={k:tk.StringVar(value=str(s[k])) for k in CROP_KEYS}
    home=pages['Ana Sayfa'].body
    ttk.Label(home,text='Oyununa odaklan.',font=('Segoe UI',23,'bold')).pack(anchor='w')
    ttk.Label(home,text='İngilizce diyalogları yakala, Türkçe altyazıyla takip et.',foreground=MUTED).pack(anchor='w',pady=(4,22))
    game=card(home,'Oyun profili')
    r=row(game);w.game_combo=ttk.Combobox(r,textvariable=w.game,values=game_names(s),state='readonly')
    w.game_combo.pack(side='left',fill='x',expand=True)
    ttk.Button(r,text='+ Yeni oyun',command=w.add_game).pack(side='left',padx=(10,5))
    ttk.Button(r,text='Adını değiştir',command=w.rename_game).pack(side='left')
    roi=card(home,'Altyazı alanı','Her oyun için ayrı bir OCR alanı saklanır.')
    r=row(roi)
    w.region_canvas=tk.Canvas(r,width=160,height=90,bg='#0b1420',highlightthickness=0)
    w.region_canvas.pack(side='left',padx=(0,18))
    rr=tk.Frame(r,bg=CARD);rr.pack(side='left',fill='x',expand=True)
    w.crop_summary=tk.StringVar()
    label(rr,'Kayıtlı bölge',10,MUTED).pack(anchor='w')
    tk.Label(rr,textvariable=w.crop_summary,bg=CARD,fg=INK,font=('Segoe UI',10)).pack(anchor='w',pady=4)
    ttk.Button(rr,text='OCR Bölgesini Düzenle…',command=w.open_region_editor).pack(anchor='w',pady=(5,0))
    control=card(home,'Canlı çeviri')
    w.connection_var=tk.StringVar(value='OBS: Bekliyor     Kamera: Bekliyor     AI: Başlatılmadı')
    tk.Label(control,textvariable=w.connection_var,bg=CARD,fg=MUTED,font=('Segoe UI',10),anchor='w').pack(fill='x',pady=(6,12))
    w.start_btn=ttk.Button(control,text='▶  ÇEVİRİYİ BAŞLAT',command=w.toggle_translation,style='Primary.TButton')
    w.start_btn.pack(fill='x')
    w.status_var=tk.StringVar(value='Hazır · Bağlantılar başlatıldığında doğrulanır.')
    tk.Label(control,textvariable=w.status_var,bg=CARD,fg=ACCENT,wraplength=650,anchor='w',justify='left',font=('Segoe UI',10)).pack(fill='x',pady=(12,3))
    w.session_cost_var=tk.StringVar(value='Bu oturum ≈ 0,00 TL')
    tk.Label(control,textvariable=w.session_cost_var,bg=CARD,fg=MUTED,font=('Segoe UI',9),anchor='w',wraplength=650,justify='left').pack(fill='x')
    last=card(home,'Son replik')
    w.last_source_var=tk.StringVar(value='Henüz İngilizce replik algılanmadı.')
    w.last_translation_var=tk.StringVar(value='Türkçe çeviri burada görünecek.')
    for prefix,var,color in [('EN',w.last_source_var,MUTED),('TR',w.last_translation_var,INK)]:
        label(last,prefix,9,ACCENT).pack(anchor='w',pady=(6,2))
        tk.Label(last,textvariable=var,bg=CARD,fg=color,wraplength=650,justify='left',anchor='w',font=('Segoe UI',11)).pack(fill='x')
    settings=pages['Ayarlar'].body
    ttk.Label(settings,text='Ayarlar',font=('Segoe UI',23,'bold')).pack(anchor='w',pady=(0,18))
    api=card(settings,'Yerel çeviri','Model ayrı süreçte bir kez yüklenir. Otomatik indirme ve bulut fallback kapalıdır.')
    field(api,'Yerel motor Python.exe',w.local_python)
    field(api,'Model klasörü',w.local_model_path)
    ttk.Button(api,text='Model klasörünü seç…',command=w._choose_local_model).pack(anchor='w')
    r=row(api);label(r,'Çeviri modeli').pack(side='left')
    ttk.Combobox(r,textvariable=w.local_engine,values=['ct2-marian','argos-ct2'],state='readonly',width=23).pack(side='right')
    r=row(api)
    for title,var,values in [('Aygıt',w.local_device,['cpu','cuda']),('Hesaplama',w.local_compute,['int8','int8_float16','float32'])]:
        label(r,title).pack(side='left',padx=(0,8));ttk.Combobox(r,textvariable=var,values=values,state='readonly',width=14).pack(side='left',padx=(0,18))
    field(api,'Eşzamanlı çeviri (CPU 1–4 / GPU 1)',w.local_workers)
    field(api,'İşçi başına CPU iş parçacığı',w.local_threads)
    w.cost_var=tk.StringVar()
    tk.Label(api,textvariable=w.cost_var,bg=CARD,fg=MUTED,wraplength=650,justify='left',anchor='w',font=('Segoe UI',9)).pack(fill='x',pady=6)
    output=card(settings,'Altyazı görünümü','OBS Browser Source adresi ve mevcut TV/yayın düzeni korunur.')
    r=row(output);field(output,'Yazı boyutu',w.font_var);field(output,'Alttan mesafe (%)',w.bottom_var)
    ttk.Checkbutton(output,text='Windows monitöründe de göster',variable=w.show_desktop).pack(anchor='w')
    w.monitor_var=tk.StringVar();w.monitor_combo=ttk.Combobox(output,textvariable=w.monitor_var,state='readonly');w.monitor_combo.pack(fill='x',pady=5)
    tools=card(settings,'Bağlantı ve tanılama','Sanal kamera yalnız Source → filtresiz ham PS5 capture card girdisini okur.')
    r=row(tools);label(r,'Ham capture card kaynağı').pack(side='left')
    w.source_combo=ttk.Combobox(r,textvariable=w.source,state='readonly');w.source_combo.pack(side='left',fill='x',expand=True,padx=10)
    ttk.Button(r,text='Kaynakları getir',command=w.load_sources).pack(side='right')
    ttk.Checkbutton(tools,text='API’siz OCR tanılama modu',variable=w.diagnostic_mode).pack(anchor='w')
    ttk.Checkbutton(tools,text='Ayrıntılı yerel günlük (hassas OCR metni içerir)',variable=w.diagnostic_logs).pack(anchor='w')
    r=row(tools)
    for title,cmd in [('OCR testi',w.test_ocr),('Yerel çeviri testi',w.test_ai),('Örnek altyazı',w.demo)]:
        ttk.Button(r,text=title,command=cmd).pack(side='left',padx=(0,8))
    w.advanced_open=tk.BooleanVar(value=False)
    adv=card(settings,'Gelişmiş ayarlar')
    details=tk.Frame(adv,bg=CARD)
    def disclose():
        if w.advanced_open.get():details.pack(fill='x',pady=(8,0))
        else:details.pack_forget()
    ttk.Checkbutton(adv,text='Sorun giderme ve teknik ayarları göster',variable=w.advanced_open,command=disclose).pack(anchor='w')
    field(details,'OBS WebSocket portu',w.obs_port)
    field(details,'OBS parolası',w.obs_password,secret=True)
    field(details,'OBS koleksiyon dosyası',w.camera_config)
    ttk.Button(details,text='Koleksiyon JSON dosyasını seç…',command=w._choose_camera_config).pack(anchor='w',pady=5)
    field(details,'OCR aralığı (sn)',w.interval)
    r=row(details);label(r,'OCR planı').pack(side='left')
    ttk.Combobox(r,textvariable=w.capture_schedule,values=['fixed_fast','adaptive'],state='readonly').pack(side='right')
    label(details,'Doğrulanmış yapılandırma: 960 × 540 · bounded960_cpu2',9,MUTED).pack(anchor='w',pady=5)
    label(details,'Mevcut oyun bağlamı / terim notları',10).pack(anchor='w')
    w.lore_text=tk.Text(details,height=3,wrap='word',bg='#223246',fg=INK,insertbackground=INK,relief='flat',font=('Segoe UI',10))
    w.lore_text.pack(fill='x',pady=5);w.lore_text.insert('1.0',s['lore'])
    r=row(details)
    ttk.Button(r,text='OBS altyazı katmanını aç',command=w.open_overlay).pack(side='left')
    ttk.Button(r,text='SRT dışa aktar',command=w.export_srt).pack(side='left',padx=8)
    label(details,'Yerel OBS adresi: http://127.0.0.1:8788/overlay',9,MUTED).pack(anchor='w')
    journal=card(settings,'Uygulama günlüğü','Ham OCR gözlemleri SQLite’ta tutulur; ayrıntılı JSONL günlük varsayılan kapalıdır.')
    w.log_box=tk.Text(journal,height=5,bg='#101b29',fg=MUTED,wrap='word',state='disabled',font=('Consolas',9),relief='flat')
    w.log_box.pack(fill='x',pady=6)
    ttk.Button(settings,text='Ayarları kaydet',command=w.save_preferences,style='Primary.TButton').pack(fill='x',pady=(0,12))
    ttk.Label(settings,text='Kaydedilen görüntü ve oyun ayarları sonraki başlangıçta uygulanır.',foreground=MUTED).pack(anchor='w')
    for page in pages.values():page.bind_wheel()
    show_page('Ana Sayfa')
