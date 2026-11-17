# Altyazı flicker düzeltmesi — 17 Kasım 2026

Temel: `codex/visual-stabilization`, `a5572cb057629dbc6eedad2b73eb61498e5dfc9e`.
Yeni dal: `codex/subtitle-flicker-fix`. Ana dal, PR #3, önceki EXE ve profiller korunur.

## Gözlenen hata ve kanıtın sınırı

`E:\OBS Video` içindeki kullanıcının belirttiği ham video erişilebildi: 1920×1080, 60 fps, 61,68 saniye. Türkçe overlay içermiyor. 8–11,5, 22,5–26 ve 46–50 saniyelerinden 20 fps ile toplam 223 örnek, mevcut kayıtlı bölge ve mevcut RapidOCR profiliyle işlendi. Ağ bağlantısı engellendi; mevcut OCR model dosyaları kullanıldı. Video, kırpımlar, ham OCR ve özel SQLite içerikleri Git'e eklenmedi.

**Değiştirilmemiş video OCR tekrarında üç aralıkta da tek kaynak/iş ve ilk sonuçtan sonra sıfır boş snapshot bulundu.** Bu ham video, kullanıcının gördüğü Türkçe flicker'ın her olayını doğrudan kanıtlamıyor. Gerçek uygulamanın aynı oturum kaydında ilk aralıkta 30 gözlemin 10'u, son aralıkta 33 gözlemin 6'sı boş; orta aralıkta 23 gözlem boş değil. Bunlar kullanıcı görüntüsünün DOM/overlay zaman çizelgesi değildir. Kayıt başlangıcı veya yeni repliğin ilk çeviri beklemesi, devam eden replikteki flicker diye sayılmadı.

Kod ve kontrollü tekrar oynatmanın kanıtladığı yol:

1. Aynı İngilizce hâlâ görüntüdeyken OCR birkaç gözlem boş dönebilir.
2. Eski tracker iki kayıp + 120 ms sonrasında track'i bitirir; `live_sources` kaynağı kaldırır ve işi iptal eder. Sonraki okuma yeni track/iş oluşturur. 600 ms stale koruması da bağımsızdır.
3. Yeni iş hazır olana kadar sunucu gerçekten boş blok gönderir. Browser'ın boş durumu uygulaması bu yolda doğru davranıştır; dolu snapshot'ı kendiliğinden silen bir DOM hatası kanıtlanmadı.
4. Uzun aynı replikte izole `I/l/Il` OCR karışmaları eşdeğer sayılmayınca kaynak değişimi, yeniden iş ve aynı boş durum oluşur. Önceki yerel günlük incelemesi de aynı konuşma için yedi ayrı işi doğrulamıştı.

Özgün canlı sunucu/DOM kaydı bulunmadığından, bunların kullanıcının gördüğü **bütün** kesintilerin tek nedeni olduğu iddia edilmez. Kaynak gecikmesi, kamera/OBS kare farkı veya farklı OCR bozulmaları gerçek yeni testte hâlâ araştırılabilir.

## Küçük düzeltme

`capture/source_evidence.py`, her kabul edilmiş track için yalnız kendi OCR kutusundaki parlak harf izlerini ve koyu çevresini tutar. Arka planın metin kanıtı olmaması için OCR kutuları, ardışık doğrulanmış izler ve küçük bileşen elemesi kullanılır. Kısa OCR kaybında her yeni karede aynı izler, yerel küçük alanlar ve çevre tekrar doğrulanır. Güven yoksa önceki bitiş davranışı uygulanır. Uniform görüntü kanıt sayılmaz.

Destek son **gerçek OCR** gözleminden en fazla 450 ms kullanılabilir; görüntüden üretilmiş destek kendi süresini yenileyemez. Bu, 120 ms debounce veya 600 ms stale süresini artırmak değildir. Görüntü değiştiğinde normal kaldırma kuralları geçerlidir. Kamera/OCR tamamen durursa stale koruması çalışır.

Harf desteği yalnız en az 18 karakter/dört kelime içeren, önceden doğru `I` okunmuş replikte, belirli fiilden önceki izole `l/Il` için uygulanır. Aynı konuşmacı, bölge ve görüntü kanıtı gerekir. Global fuzzy eşleştirme yoktur. Okunabilir farklı B, isim, olumsuzluk, sayı, kısa söz veya başka konuşmacı bu destekle birleştirilmez. Yeni B çevirisi beklenirken eski A gösterilmez; A→B→A yeni işlerdir. Ham OCR kayıtları değiştirilmez; destek nedenleri mevcut opt-in yerel tanılama günlüğüne yazılır.

Model/çeviri işçisi/CUDA/OCR ayarları, sunucu, frontend, maske ve konum hesapları değiştirilmedi. Kaynak/iş kimliği korunduğu için aynı replikte gereksiz DOM silme/yeniden oluşturma yolu ortadan kalkar. Yalnız siyah maskeyi tutan ayrı, süresiz bir yol eklenmedi.

## Tekrar oynatma ve regresyonlar

Ölçümler mantıksal video zamanında gerçek OCR çıktıları ve görüntü pikselleriyle yapıldı. Çeviri için 100 ms sonra tamamlanan sentetik yerel sonuç kullanıldı; model/PS5/OBS gecikmesi ölçümü değildir. 20, 10 ve yaklaşık 6,67 fps örneklemeleri kullanıldı.

| Deney | Eski kaynak | Düzeltilmiş kaynak |
|---|---|---|
| Normal video, üç aralık ve üç hız | Aralık başına 1 iş, 0 kesinti | Aralık başına 1 iş, 0 kesinti |
| Aynı görüntüde kontrollü 300 ms boş OCR, üç aralık ve üç hız | Her aralıkta 2 iş, 300 ms boş snapshot | Her aralıkta 1 iş, 0 boş snapshot |
| İki aralıkta kontrollü `I/l/Il`, 20 fps | Aralık başına 23 iş, toplam 1.150 ms boş snapshot | Aralık başına 1 iş, 0 boş snapshot |

Üçüncü aralıkta harf enjeksiyon koşulu tetiklenmedi; harf düzeltmesi için başarı kanıtı sayılmadı. Özel tekrar oynatma izleri OCR zamanı/güveni, track ve kaynak kimliği, iptal nedeni, job kimliği ve tam sunucu snapshot'ını ilişkilendirir; özel yerel test klasöründe tutulur. Tarayıcı tarafı ayrıca gerçek overlay JavaScript'ini çalıştıran deterministik DOM/ağ/saat harness'iyle sınanır. Bu bir OBS/CEF ölçümü değildir.

15 yeni test: birkaç boş kare, görüntü kanıtlı harf karışması ve değişmeyen ham OCR, gerçek bitiş, desteğin zaman sınırı, hızlı A→B→A, B beklerken A'nın kaldırılması, geç A sonucu, isim/olumsuzluk/sayı/konuşmacı değişimi, kutusuz OCR, durmuş capture, üç kaynağın bağımsızlığı ve değişmeyen kompakt maske/metin konumu. Mevcut bağlantı kopma/toparlanma ve 1.500 ms watchdog testleri korunur.

Tam test sonucu: **255/255 geçti**, 94,637 saniye, skip yok (mevcut 240 + yeni 15). Anlam değişimi testi daha sonra güçlendirilip yeni 15 test tekrar geçirildi. Çalıştırma: `python -m unittest discover -s tests -v`. Yerel test ortamı ve paketleme ortamı değiştirilmedi; yeni bağımlılık indirilmedi.

Yeni Windows EXE paket testi de geçti: sentetik kamera + mevcut gerçek OCR, üç altyazı bloğu, bekleyen gösterim 0, HTTP ACK 204, Tk hata 0, işçiler kapandı. Kamera/PS5 ve yerel çeviri modeli bu smoke testinde kullanılmadı. Paket arşivinde yeni kaynak-görüntü modülünün bulunduğu doğrulandı. Önceki görsel, yayın öncesi ve UI EXE'lerinin SHA-256 değerleri aynı kaldı.

## Windows denemesi ve geri dönüş

Yeni kaynak: `projects/subtitle-flicker-fix`.
Yeni paket: `dist/subtitle-flicker-fix-20261117/EdizGameTranslator/EdizGameTranslator.exe`.
Başlatıcı: ana uygulama klasöründeki `FLICKER_TEST_BASLAT.bat`.
Profil: `local-data/subtitle-flicker-fix-profile`; yalnız mevcut görsel sürümün ayarlarının kopyası, eski SQLite geçmişi kopyalanmaz. Model dosyaları ve model yolu aynı kalır.

1. Önce çalışan eski çeviri uygulamasını durdurup kapatın. İki uygulama aynı 8788 portunu kullanamaz.
2. Yeni BAT'ı açın. OBS Browser Source URL'si `http://127.0.0.1:8788/overlay`; mevcut sayfanın önbelleğini yenileyin. Geçerli ham kaynak/OCR bölgesi ve `auto` yerleşimini kontrol edin.
3. Aynı uzun İngilizce dururken Türkçenin sürekliliğini; kısa sözleri; iki/üç konuşmacıyı; hızlı A→B→A'yı; B beklerken A'nın kalkmasını; gerçek bitişte maske/metnin kalkmasını deneyin.
4. OBS bağlantısını kesip geri getirin: son altyazı kalmamalı, eski sonuç dönmemeli. Önceki bağlantı watchdog'u değiştirilmedi.
5. Sorunda yeni uygulamayı kapatıp korunmuş `GORSEL_STABILIZASYON_BASLAT.bat` ile önceki sürüme dönün; OBS sayfasını yenileyin. Profil/EXE geri kopyalama veya silme gerekmez.

Ayrıntılı tanılama gerekirse uygulamadaki **Ayrıntılı yerel günlük** seçeneğini kullanıcı açabilir; varsayılan kapalıdır. Günlükler özel OCR metni içerir ve Git'e gönderilmemelidir. Yeni PS5 testinde mümkünse Türkçe overlay içeren OBS kaydı alın; ham video tek başına görünürlük anını kanıtlayamaz.

Kalan risk: görsel kanıt çok sıkı olduğundan ağır sıkıştırma, solma, renk değişimi veya daha uzun OCR kesintisinde destek reddedilebilir ve güvenli kaldırma uygulanabilir. OCR'nin okuyamadığı gerçek görüntü değişimi eski harf izlerini korursa kısa destek aralığında yanlış devam mümkün olabilir; bu yöntem tam görsel metin tanıma değildir ve kesin uçtan uca garanti vermez. Yeni sürümle fiziksel PS5/OBS testi bu görevde yapılmadı.
