# Görsel stabilizasyon — 16 Kasım 2026

Temel dal `codex/prebroadcast-stabilization`, commit `3052c60785590e0c86bec4850d0a952b8fde4720`. Geliştirme dalı `codex/visual-stabilization`. Kullanıcının bildirdiği önceki PS5/Spider-Man ve OBS bağlantı başarıları esas alındı; **bu görevde yeni EXE ile gerçek PS5/OBS testi yapılmadı**.

## 1. Bulgular ve kök nedenler

Eski auto hesapta kayıtlı maske genişliği minimum olarak alınıyordu. Varsayılan %78, kısa replikte de geniş siyah şerit oluşturuyordu. Maske merkezi/alt konumu her OCR kutusuyla yeniden hesaplanıyordu; 960×540 kaynaktaki ±5 piksel, 1080p çıktıda ±10 piksele karşılık gelebiliyor. Browser her snapshot’ta DOM/font küçültmesini yeniden çalıştırıyor, native görünüm de yalnız ham kutu/ACK değiştiğinde tekrar çizilebiliyordu. Bunlar kod ve sentetik testlerle doğrulandı; gerçek oyundaki hareketin tamamı için video ölçümü yapılmadı.

## 2. Yapılan P0 düzeltmeleri

Auto maskede kayıtlı genişlik artık minimum değil, satır kırma sınırı olarak kullanılır. Algılanan İngilizce kutusu + güvenlik payı ile Türkçe/karakter isminin Windows Segoe UI Bold üzerinden ölçülmüş alanının birleşimi alınır. Uzun Türkçe kelimeler/satırlar ortak hesapta bölünür. İngilizce uzun/Türkçe kısa durumda maske İngilizceye göre geniş kalır. İngilizce kısa/Türkçe uzun durumda gereken genişlik/yükseklik sağlanır.

Native ve OBS aynı `mask_rect`, `body_rect`, `name_rect`, ölçülmüş satırlar ve font boyutunu kullanır. Dinamik görünümde renderer’ın tekrar satır kırıp font küçültmesi önlenir. Geçersiz/eksik/aşırı yüksek OCR kutusunda kayıtlı maske kullanılır. Sayısal olarak geçerli bir OCR kutusunun hiç algılanmamış İngilizce kelimeleri kapsadığı garanti edilemez; şüpheli durumda Fixed güvenli geri dönüş seçeneğidir. Sistem fontu okunamazsa önceki hesap korunur; font/bağımlılık indirilmez.

Aynı görünür kaynak/çeviri işi için konum kilidi ve altı kaynak piksellik pay uygulanır. ±2–5 piksel jitter maske/metin koordinatlarını değiştirmez. Kutu bu payı aşarsa İngilizceyi açıkta bırakmamak için maske genişleyebilir; Türkçe gövdesinin konumu sabit kalır. Yeni replikte gerekli yeni konum kullanılır. OCR varyantlarının yeni job kimliği üretmesi durumunda, en fazla 350 ms içinde ve yalnız ±5 piksel yakınlıkta önceki koordinat kullanılabilir. Bu bellekte metin/maske/görünürlük taşınmaz; boş snapshot boş kalır. Oturum ve geometri ayarı değişince kilitler sıfırlanır.

Karakter adı eklenip kaldırılınca gövde gereksiz kaydırılmaz. Aynı işte maske küçültülmez; bir sonraki işte yeniden kompakt hesaplanır. Çakışan üç gerçek kaynağın metin alanları ayrılır, birleşik maske İngilizce kutularını örtmeye devam eder. Aynı görsel veride DOM/native çizimi tekrarlanmaz. **Fixed hesap fonksiyonu eski sürümle AST düzeyinde aynı kaldı.**

## 3. Bağlantı güvenliği ve P1 maskenin yaşam döngüsü

Önceki 500 ms SSE heartbeat, 800 ms HTTP sınırı, 1.500 ms watchdog, eski bağlantı/istek ve animation ACK korumaları korunur. Bağlantı toparlanma kodu önceki dalla birebir karşılaştırıldı; bağlantı regresyonları yeniden çalıştırıldı.

OCR kaybında yalnız maskeyi tutan ayrı bir görünürlük yolu bu görevde eklenmedi. İki boş gözlem + 120 ms / 600 ms stale kuralları aynıdır; yeni konuşma hazır değilken eski Türkçe veya eski maske tutulmaz. Sonraki çalışma için ham görüntüde ilgili satırın gerçekten hâlâ bulunduğunu kanıtlayan ROI kararlılığı gerekir. Bu kanıt, kaynak değişiminde eski Türkçeyi hemen silme ve bağlantı kaybında kesin maske sınırıyla birlikte OBS/native üzerinde sınanmalı. Yayın öncesinde bu daha riskli değişiklik ertelendi.

## 4. Tekrarlanan günlük kayıtlarının gerçek incelemesi

İlgili yerel SQLite salt okunur açıldı. Kullanıcının belirttiği 19:01:11–19:01:12 aralığında aynı Türkçe sonuç için **yedi ayrı subtitle ve yedi ayrı translation job** bulundu. Aynı konuşmacı ve neredeyse aynı kutuda üç İngilizce OCR varyantı var: `I/l` değişimi ve ek `l`. Mevcut korumalı karşılaştırma bunları eşdeğer kabul etmiyor; kaynak yeniden oluşturuluyor. Bu yalnız UI log tekrarı değil.

Altı işte `processing_ms` mevcut: yeniden model işleme yapılmış. Son işte bu metrik yok ve toplam süre sıfıra yakın; lookup/cache yoluyla uyumlu. Tarihsel route alanı kaydedilmediğinden bunun cache mi sözlük mü olduğu kesin ayrılamıyor. Ham oyun metni, veritabanı veya kullanıcı ayarı commit’e eklenmedi.

Anlam/isim/olumsuzluk korumasını yayın öncesinde gevşeten bir fuzzy eşleştirme veya metne göre UI log bastırma uygulanmadı. Gerçek A→B→A ve farklı konuşmacılar korunur. Sonraki dar görev: bu OCR harf karışmalarını çok kare/bölge/konuşmacı kanıtıyla doğrulamak; job kimliği ve route’u tanılamada görünür kılmak. Geometri kilidi yeni işlerin ufak kutu farklarını azaltır, gereksiz çeviri işlerini ortadan kaldırdığı iddia edilmez.

## 5. Test ve görsel kanıt

- Başlangıçtaki 218 testin tamamı geçti (154,3 s).
- Son kaynakta **240/240 test geçti**, 168,4 s; skip yok. Önceki bağlantı ve kaynak-güncellik testleri korunuyor.
- Yeni Windows EXE sentetik kamera + mevcut gerçek OCR smoke testini geçti: üç blok, bekleyen gösterim=0, HTTP ACK=204, Tk hata=0, işçiler kapandı.
- Paket arşivinde yeni dinamik geometri ve önceki watchdog kodu doğrulandı.
- Gerçek Tk glyph sınırları dört tuval boyutunda maskenin içinde kaldı. Bu, gerçek OBS/CEF/PS5 testi değildir.

Yeni testler kısa/uzun kaynak ve Türkçe, tek/çok satır, isimli/isimsiz, ±2–5 piksel, yeni iş kimliği ve oturum sıfırlama, 350 ms geometri sınırı, üç kaynak, bilinmeyen kutu, 1080p/720p/540p/4:3 letterbox, gerçek Tk glyph sınırları, DOM yeniden çizimi, Fixed/Auto geçişi ve bağlantı kaybını kapsar. Mevcut tek kare OCR, geç çeviri, A→B→A ve bağlantı testleri korunur. Yeni bağımlılık/model indirilmedi.

[Sentetik önce/sonra maskeleri](../images/visual-mask-comparison.png): kısa örnekte %78 → %17,9; uzun İngilizce örneğinde %78 → %65,9; uzun Türkçe örneğinde %78 → %75,3. Oranlar yalnız belirtilen sentetik kutulara aittir, gerçek PS5 ölçümü değildir. Görsel `python tools/run.py visual_mask_compare` ile üretilebilir.

## 6. Değişen dosyalar ve Git

Üretim: `subtitles/layout.py`, `subtitles/canvas_view.py`, `subtitles/desktop_overlay.py`, `subtitles/overlay_view.py`, `subtitles/overlay_server.py` (`src/ediz_game_translator` altında).

Test/kanıt: `tests/test_visual_layout.py`, `tests/test_overlay_connection.py`, `tests/overlay_connection_cases.js`, `tools/smoke/visual_mask_compare.py`, karşılaştırma PNG’si ve bu rapor.

`capture`, `translation`, `storage`, `app.py`, `core.py`, `live_display.py`, `requirements` ve mevcut ayarlar değiştirilmedi. `main`/PR’lar birleştirilmedi; yeni dal yereldir, GitHub’a push yapılmadı. Commit SHA teslim yanıtında ve yerel teslim kaydındadır.

## 7. Yeni Windows EXE ve geri dönüş

Kaynak: `projects/visual-stabilization`. Yeni EXE: `dist/visual-stabilization-20261118/EdizGameTranslator/EdizGameTranslator.exe`. Başlatma: ana klasörde `GORSEL_STABILIZASYON_BASLAT.bat`. Yalnız mevcut kullanıcı ayarlarının kopyası yeni `local-data/visual-stabilization-profile` içine alındı; eski profiller/SQLite/model/ortamlar korunur. Test profilinin geçmişi ayrı başlar.

Önce eski çeviri uygulamasını durdurup kapatın; iki uygulama 8788 portunu paylaşamaz. Yeni BAT’ı açın, OBS Browser Source geçerli sayfa önbelleğini yenileyin. URL `http://127.0.0.1:8788/overlay` olarak kalır. Kompakt maske için Altyazı Tasarımı → Yerleşim `auto` olmalı. `fixed` kayıtlı maske davranışını korur.

Sorunda yeni uygulamayı kapatın, korunmuş `STABILIZASYON_TEST_BASLAT.bat` ile stabilizasyon sürümüne dönün ve OBS sayfasını tekrar yenileyin. İki eski EXE ve mevcut BAT üzerine yazılmadı; hash’leri kontrol edildi. Eski klasör veya ortam silinmedi.

## 8. Gerçek PS5 üzerinde kalan kontroller

Yeni EXE’de kısa İngilizce/uzun Türkçe ve tersi; ekran kenarındaki, iki satırlı ve iki/üç konuşmacılı altyazılar; isimli/isimsiz geçişler; hızlı A→B→A; OCR kaybı ve OBS bağlantı kopması denenmeli. Özellikle algılanmamış kelimelerin kompakt maske dışında kalmadığı ve kullanılan OBS tuval/kırpma dönüşümü kontrol edilmeli. Sorunlu oyun profilinde Fixed kullanılabilir.

## 9. Yayın sonrasına bırakılanlar

Ham görüntü kanıtına bağlı bağımsız maske yaşam döngüsü; kontrollü I/l OCR kararlılığı ve job/route tanılaması; gerçek CEF/native font ve farklı monitör/DPI karşılaştırması. Sistem fontları ve piksel yuvarlamaları küçük çizim farkları oluşturabilir. CEF/işletim sistemi tamamen durursa JavaScript watchdog fiziksel ekran süresi garantisi vermez. Bu görevde GTA VI veya PS5→TV gecikmesi/çeviri kalitesi ölçülmedi.
