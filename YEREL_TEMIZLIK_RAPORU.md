# API arşivi ve yalnız yerel sürüm — 16 Kasım 2026

## Arşiv, dallar ve işlem sırası

- [Eski API sürümü arşivi](https://github.com/Ediz500/EdizGameTranslator/tree/archive/openai-api-legacy)
- [Temizlik dalı](https://github.com/Ediz500/EdizGameTranslator/tree/codex/local-only-cleanup)
- Yeni taslak PR için base `codex/low-latency-local`, head `codex/local-only-cleanup`.
  PR bağlantısı teslim mesajında paylaşılır. PR #1 açık taslak olarak korunur.

Önce güncel dallar fetch edildi. `main` SHA:
`11560899331b244956af345d5cc1fd4c790896da`; yerel geliştirme dalı SHA:
`93609e2dbe98d5591dbf710d1cbc7643d53199bb`. Geçmiş ve dosya güvenliği
doğrulandıktan sonra arşiv dalı, main'in **aynı commit'ine** normal push ile
oluşturuldu. GitHub üzerinden aynı SHA ve değişmemiş main doğrulandı. Arşiv
doğrulaması tamamlanmadan uygulama temizliğine başlanmadı.

Temizlik ayrı worktree ve `codex/local-only-cleanup` dalında yapılmıştır.
Kaydedilmemiş özgün çalışma dosyaları, eski EXE'ler ve ortamlar korunmuştur.
Main'e commit, dal silme, geçmişi yeniden yazma veya force-push yapılmaz.
Yeni commit'lerde GitHub noreply kimliği kullanılır.

## Kaldırılan çalışan bileşenler

- `core.py`: `TranslationEngine`, `TranslationResultError`, `TranslationUsage`,
  `BudgetLedger`, `ContextMemory`, fiyat tablosu, ücret/token hesaplamaları,
  bulut prompt sabiti ve yalnız bunların kullandığı importlar kaldırıldı.
- `model_config.py`: bulut model kimliği, fiyat ve istek sözleşmesi modülü
  aktif daldan kaldırıldı. Tam eski kaynak arşiv dalında bulunur.
- `app.py`: `legacy_translate_worker`, `legacy_test_ai`, `forget_api_key`,
  `_store_ledger`, bütçe nesnesi, API runtime anahtarı, ücret olayları ve
  maliyet günlükleri kaldırıldı. Yerel test/çeviri olayları artık ücret alanı
  taşımaz. OBS parola yardımcıları yalnız `obs_password` adına izin verir.
- `app_ui.py`: gizli/eski model ve anahtar değişkenleri, bütçe/kur değişkenleri,
  geçmiş maliyet ve oturum maliyeti göstergeleri kaldırıldı. Aynı iki sayfada
  yerel motor, CPU/CUDA, modelin sıcaklığı, son çeviri süresi ve bekleyen işler
  gösterilir. Görünüm ve kullanıcı akışı yeniden tasarlanmadı.
- `subtitle_store.py`: yeni işlerde token/ücret/çağrı sayımı yapılmaz. Yerel
  gecikmeler `translation_start_mono`, motor süresi ve kapasite beklemesi ile
  izlenir. `overlay_server.py` ve `translation_dispatch.py` artık bir bulut
  kullanım/maliyet nesnesi oluşturmaz.
- `package_checks.py` ve `launcher.py`: SDK sözleşme/ücret denemeleri çıkarıldı;
  doğrulama gerçek yerel işçi, OCR ve gösterim üzerine kuruldu.

## Bağımlılıklar ve paket

`requirements.txt` içinden OpenAI SDK kaldırıldı. Kilit dosyası, kurulu
dağıtımların gerçek bağımlılık metadata'sından yerel Windows çalışma yoluna
göre çıkarıldı. Şu 13 eski constraint artık çalışma kilidinde yok:

`openai`, `httpx2`, `httpcore2`, `jiter`, `anyio`, `h11`, `pydantic`,
`pydantic-core`, `annotated-types`, `sniffio`, `truststore`,
`typing-extensions`, `typing-inspection`.

OBS için `obsws-python`, `websocket-client` ve `keyring`; kamera için
`pygrabber`, `comtypes`, OpenCV; OCR için RapidOCR/ONNX Runtime ve gerekli
bağımlılıkları korunur. Yerel çalışma kilidinde 32 dağıtım bulunur.

`EdizGameTranslator.spec` artık SDK/SDK HTTP paketlerini toplamaz; bunları açıkça
dışlar. Temiz SDK'sız ortamdan oluşturulan paketin Analysis listesinde bu
modüller ve `model_config` yoktur. Çeviri ağırlıkları pakette yoktur. Paket
boyutu yaklaşık 281 MiB'dir; bu yalnız yerel build çıktısıdır, Git'e eklenmez.

## Kullanıcı verilerinin korunması

- Eski ayarlar okunur; oyun, notlar, OCR bölgeleri ve genel yerel ayarlar
  korunur. Eski bulut alanları güvenle görmezden gelinir ve yeni ayarlara
  yazılmaz. Geçersiz/eski bütçe alanı artık yerel uygulamayı engellemez.
- Eski harcama JSON dosyası açılmaz, güncellenmez veya silinmez. Eski API
  anahtarına Windows kasasında okuma/yazma/silme işlemi yapılmaz. OBS parolası
  yönetimi korunur.
- SQLite geçişi eklemelidir (`user_version=4`). Mevcut metinler, çeviriler,
  eski token/maliyet sütunları ve değerleri yerinde kalır. Eski başlangıç
  zamanından yeni yerel başlangıç sütununa bir kez kopyalama yapılır. Eski
  finans sütunları yerel çalışma tarafından kullanılmaz veya güncellenmez;
  yeni veritabanlarında oluşturulmaz.
- Önceki oturumun eski gösterim kuyruğunu yeniden açmayan güvenli yeniden
  başlatma davranışı korunur. Veritabanı veya tablo drop edilmez.
- Yerel benchmark'ın eski kayıtlı Luna referanslarını salt okunur incelemesi
  korunur. Bu, çalışan API yolu değildir; yeni sütunsuz yerel şemadan da export
  yapılabilir. Tarihsel model adları ve anonim performans ölçümleri silinmez.

## Korunan hızlı yol

`light_translation.py`, `local_translation.py`, `benchmark_light.py`, capture,
RapidOCR profilleri, değişim algılayıcı, OBS Virtual Camera güvenliği, kare
paylaşımı, üçlü gösterim/sayaç mantığı, overlay HTML/JS, bölge düzenleyicisi ve
oyun profili kaynakları geliştirme tabanıyla aynıdır. SSE'nin uç noktası ve
renderer ACK davranışı korunur; yalnız maliyet nesnesi bağlantısı çıkarılır.
Genel OCR temizleme/seçim yardımcıları ve SRT zaman çizelgesi korunur.

Yeni motor veya model eklenmedi; model indirilmedi. Mevcut OPUS-MT / CT2 CUDA
ağırlıkları ve ayrı sıcak işçi kullanıldı. Temiz OCR ortamına ağırlıklar önceki
ortamdan kopyalandı; internetten yeni OCR modeli indirilmedi. Maske, renkli isim,
kuyruksuz gösterim veya çeviri kalitesi değişikliği yapılmadı.

## Test ve doğrulamalar

| Kontrol | Sonuç |
|---|---|
| Temizlik öncesi mevcut regresyonlar | 195/195 geçti |
| SDK bulunmayan temiz Windows ortamında geçerli regresyonlar | 179/179 geçti |
| Python sözdizimi, CPython 3.12 x64/Tk ve pip check | Geçti |
| SDK/SDK HTTP modüllerinin ortamda bulunmaması | Doğrulandı |
| Bulut importlarını engelleyerek normal GUI/yerel yol | Geçti |
| Eski ayar, kasa erişimi ve SQLite veri koruma testleri | Geçti |
| Gerçek RapidOCR + gerçek CUDA işçisi + sentetik GUI hattı | Geçti |
| Gerçek OBS üzerinde salt okunur güvenlik kontrolü | 100/100 geçti |
| Temiz Windows EXE, bölge editörü, tek kamera, üç blok + bekleyen iş | Geçti |
| EXE içinden gerçek CUDA çeviri ve işçinin kapanışı | Geçti |

23 geçersiz bulut/fiyatlandırma testi aktif paketten çıkarıldı; 7 yeni yerel
sınır/veri koruma testi eklendi. Protokol, oturum, OBS, OCR ve üçlü gösterim
regresyonları korunup gerektiği yerde yerel motora uyarlandı. Test sayısı yapay
olarak korunmadı. Geliştirmedeki eski test imzası ve test veritabanı handle
kapatma hatası giderildi; son kontrollerde başarısız test yoktur.

EXE testi SDK yüklenmediğini, Tk hatası olmadığını, işçilerin kapandığını,
gerçek yerel sonucun tamamlandığını ve HTTP ACK'nin çalıştığını raporladı.
Paket `dist/local-only-cleanup/EdizGameTranslator/EdizGameTranslator.exe`
konumunda ayrı oluşturuldu. Önceki dağıtımların üzerine yazılmadı.

Gerçek OBS kontrolünde değişmeyen JSON 100 kontrolde yalnız bir kez okundu.
Canlı güvenlik denetimi p50/p95 **3,19/3,98 ms**, stat **0,069/0,099 ms**,
ilk JSON okuma/ayrıştırma **2,83 ms** idi. Bu test kamera karesi yakalama veya
fiziksel PS5 görüntü testi değildir; OBS ayarları değiştirilmedi.

## Aynı ayarlarda önce/sonra ölçümü

RTX 3060 12 GB, CTranslate2 4.9.0, CUDA `int8_float16`, beam 4, tek kapasite ve
iki CPU thread. Aynı mevcut 59 kayıtlı OCR gözlemi × 3 tekrar × 2 koşu kullanıldı:
her tarafta 354 tam çeviri. Corpus ve model aynı, sıcak ölçümlere yükleme/ısınma
dahil değil. İşlem sırası önce/sonra/önce/sonra; test veya paket derlemesiyle
eşzamanlı çalıştırılmadı. Sistem genelindeki arka plan yükü tam sabitlenemedi.

| Tam sonuç (işçi gidiş/dönüş dahil) | Önce p50 / p95 / max | Sonra p50 / p95 / max |
|---|---:|---:|
| Tüm replikler, n=354 | 47,4 / 106,9 / 128,8 ms | 48,0 / 110,2 / 138,0 ms |
| Kısa, n=270 | 39,4 / 75,3 / 100,6 ms | 40,7 / 76,4 / 110,2 ms |
| Uzun, n=84 | 90,6 / 122,7 / 128,8 ms | 90,2 / 129,1 / 138,0 ms |

Tek koşuların p50/p95 değerleri: önce **45,3/108,0** ve **48,2/106,9**;
sonra **48,0/120,0** ve **48,5/104,8 ms**. Yalnız en iyi koşu seçilmedi.
İlk süreç→sıcak hazır süreleri önce **1488/1404**, sonra **1442/1291 ms**.
İşçi RAM tepesi önce **784,7 MiB**, sonra **785,8 MiB**; GPU toplam tepe kullanımı
önce **1968 MiB**, sonra **1962 MiB**. GPU değeri model dışındaki süreçleri de
içerir. Her iki tarafta çalışma hatası **0/354**; çıktı metinlerinin toplu
SHA-256 değerleri eşittir. Bu kalite doğruluğu puanı değildir.

Birleşik ölçümde p50 yaklaşık %1,3, p95 %3,1 daha yüksektir. İki koşu ve
kontrol edilemeyen arka plan yükü, birebir eşit hız veya değişimin sebebi için
istatistiksel kanıt sağlamaz. Önceki yaklaşık 49/109 ms sonucuna yakın bir
model süresi gözlenmiştir; hızlanma veya kesin değişmeme iddiası yapılmaz.
Bu süreler OCR, gösterim kuyruğu ve fiziksel TV'yi kapsamaz.

## Güvenlik ve kalan kapsam

Arşiv push'undan önce main + geliştirme geçmişindeki 12 commit ve 120 blob;
anahtar/token/private-key desenleri, literal parolalar, kimlik bilgisi taşıyan
URL'ler, özel ayar/veritabanı/credential export ve büyük ikili dosyalar için
tarandı. Bulguların doğrulanması için dış servise istek gönderilmedi.
Bilinen sentetik test değerleri ve kimliği/metni kaldırılmış eski zamanlama
fixture'ı ayrıca incelendi. Gerçek veya olası gizli bilgi bulgusu çıkmadı.
Temizlik dalı ve gönderilecek geçmiş için push öncesi tarama tekrar yapılır;
şüpheli değer görülürse push durdurulur, değer açıklanmaz.

Yalnız kaynak, test, bağımlılık/kurulum tarifleri ve bu toplu sonuçlar yüklenir.
Ham corpus/yanıtlar, özel kullanıcı profili, veritabanı, kayıtlar, ortamlar,
model ağırlıkları ve EXE/build çıktıları Git'e alınmaz.

Gerçek PS5 video yakalama ve fiziksel TV uçtan uca ölçümü bu temizlik görevinde
yapılmadı. İnsan etiketli recall ve çeviri kalite onayı önceki görevdeki gibi
açık kalır. Bu rapor bu hedeflerin tamamlandığını iddia etmez. Açık taslak PR'lar
birleştirilmez; main ve arşiv kodu yerinde kalır.
