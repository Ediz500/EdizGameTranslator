# Modern arayüz ve canlı kaynak senkronizasyonu

Tarih: 16 Kasım 2026. Dal: `codex/ui-live-sync-redesign`; base: `codex/local-only-cleanup` (`1649bd0`). Ana dal ve eski API arşivi değiştirilmedi. Çalışma ayrı Git worktree’de yapıldı; orijinal, kaydedilmemiş değişiklikleri olan kaynak klasörü korunuyor.

## Sonuç

Beş sayfalı CustomTkinter Windows kontrol paneli, oyuna özel maske/isim ayarları ve kaynak görünürlüğüne bağlı altyazı uygulanmıştır. Normal oturumda okuma sayacı veya geçmiş konuşma FIFO gösterimi bulunmaz. Güncel kaynak için eşleşen çeviri hazırsa gösterilir; diğer hazır işler yalnız geçmişte kalır. Üç eşzamanlı gerçek kaynak ayrı korunur.

Gösterim SQLite’taki `live_sources` durumuna bağlıdır. Bir boş gözlem sonraki karede düzelebilir; en az iki boş gözlem ve 120 ms debounce sonrasında kaynak kapatılır. Kaynak konumunda yeni konuşma/düzeltme geldiğinde eski sonuç bekletilmez. Son OCR gözlemi 600 ms’den eskiyse katman güvenli biçimde kapanır. Aynı kısa sözün gerçek tekrarları, farklı konuşmacılar ve A → B → A yeni kayıtlar üretir. Model işçisi ekran durumunu değiştiremez; tamamlanmış işin kaynağı artık görünmüyorsa çıktı geçmişte saklanır.

Maske yalnız çeviri hazırken çizilir. Tam siyah zemin, beyaz diyalog ve ayrı renkli isim hem Browser Source hem native Canvas için uygulanır. Normalleştirilmiş OCR kutusu / oyun profili fallback’i ortak `arrange_blocks` ve contain/letterbox hesabına girer. Font boyutu 1920×1080 referansına göre ölçeklenir; 960×540 yakalama nedeniyle iki kez büyümez. Ham görüntünün pikselleri değiştirilmez. Özel OBS kırpma/esnetme dönüşümleri ve gerçek oyun kutuları ayrıca sahada doğrulanmalıdır.

## Arayüz ve veri

Canlı Çeviri, Altyazı Tasarımı, Oyun Profilleri, Bağlantılar ve Tanılama sayfaları gerçek kontrolcüye bağlıdır. Model/OCR yükü işçi süreç/thread’lerinde kalır. Görüntü önizlemesi son kareyi 4 FPS sınırıyla örnekler. Model yüklemesi durdurulabilir; başarısızlıkta buluta geçilmez. Bağlantı kurulmadan hazır/sıcak göstergesi yoktur; ölçülmeyen süre `—` olur. Son EN/TR alanı geçmişi gösterir; ekranda tutulacak altyazıyı belirlemez.

Oyun profili OCR ve maske ayarını ayrı saklar; yeniden adlandırmada ikisi de taşınır. Canlı oturumda profil değişimi engellenir. SRT görünürlük başlangıç/bitişlerini kullanır; aynı anda konuşan kaynakların bitişlerini birbirine bağlamaz. Manuel örnek etiketi `local:manual` oldu. Eski SQLite `api_called DEFAULT 1` alanı bulunan veritabanında yalnız yeni yerel işler açıkça 0 ile eklenir; tarihsel değerler değiştirilmez.

## Çeviri motorunun korunması

OPUS-MT revizyonu, INT8 ağırlıkları, CUDA `int8_float16`, işçi=1, thread=2 ve beam=4 korunmuştur. AST karşılaştırmasında `CT2Translator`, `worker`, `model_manifest`, `validate_capacity` aynı; `translation_memory.py` içeriği birebir aynıdır. Model/dönüştürme ortamına bu görevde paket veya ağırlık indirilmedi. Worker istemcisinde yalnız yeni paket yolu ve yükleme iptali desteği değişti.

Aynı SHA-256 korpus, 59 gözlem × 3 tekrar; her tarafta 177 tam sonuç:

| Ölçüm | Önce | Sonra |
|---|---:|---:|
| Süreçten sıcak hazır duruma | 1.503 ms | 2.185 ms |
| Model işleme p50 / p95 | 46,4 / 106,9 ms | 48,7 / 110,5 ms |
| İşçi gidiş-dönüş p50 / p95 | 46,7 / 107,1 ms | 49,5 / 110,8 ms |
| Kısa replik p50 / p95 | 40,0 / 71,9 ms | 40,3 / 82,6 ms |
| Uzun replik p50 / p95 | 87,9 / 119,7 ms | 87,8 / 121,4 ms |
| Çalışma hatası | 0 / 177 | 0 / 177 |
| İşçi RAM tepe (RSS) | 785,3 MiB | 784,3 MiB |
| Toplam GPU VRAM tepe | 1.900 MiB | 1.887 MiB |

VRAM tüm aygıtı, RSS işçi ve Windows launcher alt süreçlerini kapsar. 250 ms örnekleme kısa tepeleri kaçırabilir. Eşzamanlı OBS+OCR yük testi olarak tasarlanmadı; işletim sistemi ve diğer açık uygulamalar koşular arasında değişebilir. Sonraki sıcak p50 yaklaşık %5,0 ve p95 %3,4 daha yüksek; tek çift koşudan nedensel hız kaybı sonucu çıkarılmaz. İlk yükleme farkı ayrıca izlenmelidir. 177 çıktının metin hash’leri birebir aynı. Hiçbir kalite iyileştirmesi veya yeni doğruluk puanı iddiası yoktur. Gizli metin içermeyen [ham toplu özet](ui-performance-summary.json) ektedir.

**Bu süreler model ölçümüdür. Gerçek PS5 → capture → OCR → çeviri → OBS → TV uçtan uca ölçümü yapılmadı; 500–800 ms hedefinin başarıldığı söylenmiyor.**

## Doğrulama

- Başlangıçta 180 test geçti. Son tam koşuda **200/200 test geçti**; 100,4 saniye.
- Yeni regresyonlar: iki boş gözlem/debounce, tek kare kurtarma, geç yanıtın geçmişte kalması, üç aktif kaynak, düzeltme/genişleme, kısa gerçek tekrar, farklı konuşmacı, oturum güvenliği, maskenin ham görüntüyü değiştirmemesi, koordinat/letterbox, isim rengi/gizleme, boşken maskenin kalkması, legacy SQLite ve yükleme iptali.
- Gerçek Windows GUI testleri %125/%150 uygulama içi widget/pencere ölçeklemesiyle çalıştı; ana kontrollerin pencere içinde kaldığı ve beş sayfanın erişilebilir olduğu doğrulandı. Windows’un gerçek DPI ayarı değiştirilmedi. %150 sentetik pencere ayrıca görsel incelendi ve ekran içinde ortalandı. Çok monitör/per-monitor DPI geçişi ayrıca gerçek kullanım testi gerektirir.
- `pip check` temiz. Paket kaynakları ve import yolları yeni `src` yapısına taşındı; BAT/spec güncellendi. Tanılama kaynaklarının `.gitignore` tarafından yanlış dışlanmasına özel istisna eklendi.
- Kaynak ve yeni Windows EXE smoke testleri gerçek RapidOCR/ONNX ve mevcut CUDA işçisiyle geçti: OCR editörü, tek kamera açılışı, editör kapanırken yakalamanın sürmesi, üç güncel blok, bekleyen gösterim=0, HTTP ACK=204, Tk hata=0, işçi/süreç kapanışı, bulut SDK yüklenmemesi.
- Edge’de canlı yerel sunucu üzerinde üç diyalog, iki renkli isim ve isimsiz konuşma görsel doğrulandı. Browser Source’un HTML/SSE protokolü aynı kodu kullanır. Bu bir OBS kompozit/PS5-TV sahada doğrulaması değildir.
- Headless Chrome ile otomatik ekran yakalama denemesi zaman aşımına uğradı; bu yöntem başarı olarak sayılmadı. Bunun yerine Edge’de gerçek pencere incelendi. Paket testi tarayıcı ekran yakalamasından ayrı çalıştırıldı.
- Kaynak kaybı→kaldırma ölçümü renderer ACK tablosuna yazılır. Sentetik deterministik testte ilk boş gözlemden ACK’ye 130 ms; bu fiziksel oyun/TV ölçümü değildir. Native ACK yalnız Tk’ye çizim gönderimidir; browser ACK iki animation frame sonrasıdır.

## Görseller

Yalnız sentetik sahneler; kullanıcı ayarı, özel oyun kaydı veya API anahtarı yok:

- [Canlı ekran](../images/live-synthetic.png)
- [Altyazı tasarımı](../images/style-synthetic.png)
- [%150 uygulama ölçeklemesi](../images/live-scale-150-synthetic.png)
- [Edge’de üç altyazı](../images/browser-three-synthetic.png)

## Tasarım referansları

[CouchSubs](https://github.com/yorulmazsinan/couchsubs): başlatma, oyun ve bağlantı ayarlarını ayırma; [Tizen Subtitle Translator](https://github.com/ismkdc/tizen-subtitle-translator): bölge ve stil kontrolünü görsel önizlemeye bağlama; [Sefflex GameTranslator](https://github.com/Sefflex/GameTranslator): oyun çevirisi odaklı kontrol paneli. Üçüncü referans ilk doğrudan erişimde 404 verdi; indekslenmiş README üzerinden tasarım yaklaşımı incelendi. Hiçbir projeden kod veya lisanslı görsel kopyalanmadı. Kullanıcının HTML taslağı Edge’de incelendi; gerçek uygulama yerine kullanılmadı.

[CustomTkinter belgeleri](https://customtkinter.tomschimansky.com/documentation/) temelinde native Windows widget’ları kullanıldı. Koyu lacivert yüzeyler, turkuaz vurgu, tutarlı kartlar ve boşluklar uygulandı. Canlı sayfada model/bağlantı dekoratif olarak başarılı gösterilmez.

## Yerel klasör ve teslimat

Yeni sürümün doğrulanmış Git kopyası `projects/ui-live-sync-redesign`, derleme `dist/ui-live-sync-redesign/EdizGameTranslator`, başlatma kısayolu ana klasörde `YENI_ARAYUZ_BASLAT.bat`. Kısayol ayrı `local-data/ui-live-sync-profile` kullanır; eski ayar ve SQLite’ı değiştirmez. Eski profilden yalnız izinli ayarlar yeni profile kopyalandı. Yeni profilin geçmişi ayrı başlar.

102 üst seviye girdinin yerel envanteri ve temizlik önerileri `local-data/organization-20261116` altında tutulur; özel envanter/patch GitHub’a gönderilmez. Ana klasördeki eski kaynak/raporların bir kısmı Git ile takip edildiği veya kaydedilmemiş değişiklik içerdiği için otomatik taşınmadı. Eski EXE, model, CUDA ve Python ortamları silinmedi; disk alanı açıldığı iddia edilmez. Windows eski geliştirme worktree klasörünü açık bir Codex süreci nedeniyle taşımaya izin vermedi; bu süreç sonlandırılmadı. Bunun yerine tamamlanmış dal ayrı Git kopyası olarak projects altına alınır; eski worktree de korunur. Yeni kaynak ağacı `src`, `tests`, `tools`, `requirements`, `docs`, `examples` olarak ayrıldı. Orijinal `.gitignore` yedeklenip sonuna yalnız yeni özel klasör dışlamaları eklendi.

Public yükleme yalnız kaynak, test, örnek, sentetik görsel ve toplu performans özetidir. Model, EXE, ortam, SQLite, gerçek ayar ve özel kayıt yüklenmez. Git geçmişi ve son dosya ağacı yükleme öncesinde gizli bilgi/büyük dosya açısından taranır. Taslak PR yalnız cleanup dalını hedefler; main/arşiv/PR #1/#2 birleştirilmez veya kapatılmaz.

## PS5 denemesinde kalan kontroller

Gerçek oyun OCR kutularının İngilizceyi tam kapatması, hızlı sahne değişimleri ve konuşma araları, birden fazla konuşmacı, OBS Browser Source + masaüstü katmanının aynı kompozisyonda örtüşmesi, gerçek Windows DPI/monitör geçişleri ve PS5→TV gecikmesi kullanıcı donanımında doğrulanmalıdır. İşçi hızı bu kontrollerin yerini tutmaz.
