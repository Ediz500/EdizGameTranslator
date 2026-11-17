# Ediz Game Translator — Canlı Yerel Sürüm

Windows üzerinde capture card görüntüsündeki İngilizce oyun repliklerini OCR ile okuyup yerel OPUS-MT/CTranslate2 motoruyla Türkçeye çevirir. CustomTkinter kontrol paneli, OBS Browser Source ve tıklamaları geçiren Windows altyazı katmanı içerir.

Bu geliştirme dalı: `codex/subtitle-flicker-fix`; inceleme tabanı `codex/ui-live-sync-redesign`. **Gerçek PS5 testinde flicker, İngilizcenin zaman zaman görünmesi ve gereksiz çeviri işleri hâlâ çözülmemiştir.** 255/255 otomatik test, gerçek oyunda kararlılık onayı değildir. Güncel sürümler, normal başlatıcı, dosya düzeni ve bağımsız inceleme kapsamı: [PROJE_DURUMU.md](PROJE_DURUMU.md).

Eski API sürümü [archive/openai-api-legacy](https://github.com/Ediz500/EdizGameTranslator/tree/archive/openai-api-legacy) dalındadır. Canlı uygulamada bulut çeviri, ücretli API veya otomatik çeviri modeli indirme yoktur. Bu aktarım görevinde model/bağımlılık indirilmedi ve uygulama davranışı değiştirilmedi.

## Canlı altyazı davranışı

Ekranda yalnız halen görünen İngilizce kaynakların hazır Türkçe çevirileri bulunur; geçmiş konuşmaları sonradan oynatan gösterim FIFO’su ve okuma sayaçları kullanılmaz. İki veya üç gerçek konuşma ayrı gösterilebilir. Kaynak kaybolunca Türkçe metin ve siyah maske birlikte kaldırılır. Tek karelik OCR kaybına karşı varsayılan 120 ms debounce ve en az iki boş gözlem kullanılır. OCR durursa 600 ms kaynak zaman aşımı görünürlüğü kapatır. Bunlar OCR gözleminden başlayan yazılım sınırlarıdır; fiziksel TV gecikmesi değildir.

Geç tamamlanan eski replik SQLite geçmişinde kalır, yeniden ekrana çıkmaz. Düzeltilen/genişleyen kaynak için eşleşen yeni çeviri beklenirken boş maske gösterilmez. Farklı konuşmacılar ve gerçek A → B → A tekrarları korunur. Eski FIFO sınıfları yalnız geçmiş karşılaştırma/test araçları için saklanmıştır; normal oturum `LiveDisplayManager` kullanır.

Maske tam siyah `#000000`, konuşma beyaz `#FFFFFF`, ayrı isim varsayılan `#50E2BE` olur. Güvenilir OCR kutusu varsa kaynak konumu, yoksa oyuna özel maske kullanılır. Kaynak ve çıktı farklı çözünürlükteyse koordinatlar normalize edilir; en-boy oranı korunarak letterbox hesaplanır. OBS ve Windows aynı maske geometrisini kullanır. OBS Browser Source boyutunu oyun tuvaliyle eşleştirin; kırpılmış/esnetilmiş özel OBS dönüşümlerini ayrıca doğrulayın.

## Gereksinimler ve kurulum

- Windows 10/11 x64, resmî [CPython 3.12 x64](https://www.python.org/downloads/windows/). MSYS2 Python kullanılmaz.
- [OBS Studio](https://obsproject.com/download), WebSocket ve Virtual Camera.
- OBS’ye DirectShow görüntüsü veren HDMI capture card.
- Çeviri için önceden hazırlanmış EN→TR model ve ayrı CTranslate2 Python ortamı. NVIDIA GPU isteğe bağlıdır; OCR CPU/ONNX üzerinde çalışır.

Kaynak klasöründe `KURULUM.bat`, ardından `BASLAT.bat` çalıştırın. Kurulum internetten Python bağımlılıklarını alır. Mevcut uyumsuz ortamı silmez; ayrı klasörde kurulum yapın. Eşdeğer PowerShell komutları:

```powershell
py -3.12 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-win\Scripts\python.exe -m pip check
.\.venv-win\Scripts\python.exe launcher.py
```

RapidOCR ilk kullanımda gerekli OCR ONNX dosyası yerelde yoksa indirebilir. Tam çevrimdışı makinede, `requirements/windows-lock.txt` ile uyumlu RapidOCR `models` önbelleğini önceden hazırlayın. Çeviri modeli uygulama açılırken indirilmez. EXE paketine OCR kaynakları dahil edilir; OPUS çeviri ağırlıkları dahil edilmez.

## PS5, capture card ve OBS bağlantısı

1. PS5 HDMI çıkışı → capture card HDMI IN. İsteğe bağlı HDMI OUT → TV. USB → Windows PC.
2. OBS’de **Video Capture Device** kaynağını ekleyin; kaynak adı örneğin `PS5 Raw Capture`. OCR girdisi için kaynağa altyazı/renk/ölçek filtresi eklemeyin.
3. OBS WebSocket sunucusunu açın (genellikle 4455). Bağlantılar sayfasında portu/parolayı girip kaynakları getirin. OBS parolası Windows kimlik kasasında tutulur; ayar dosyasına yazılmaz.
4. OBS Virtual Camera ayarlarında **Output Type = Source**, kaynak = filtresiz capture card girdisi. Sanal Kamerayı OBS’den başlatın. Uygulama OBS ayarlarını değiştirmez. Program/Preview kompozit görüntüsü OCR’ye verilmez; canlı yön, aktif koleksiyon, filtreler ve kaynak türü doğrulanamazsa yakalama durur.
5. Gerekirse aktif OBS koleksiyon JSON dosyasını seçin. Uygulama koleksiyon dosyasını ve OBS günlüğünü salt okunur inceler. Koleksiyon/yön değişirse yeniden başlatın.
6. Bağlantılar’da yerel motor Python yolunu, model klasörünü ve CPU/CUDA ayarını seçin. Oyun Profilleri’nde OCR bölgesini düzenleyip kaydedin.
7. OBS’ye Browser Source ekleyin: `http://127.0.0.1:8788/overlay`. Boyutunu oyun tuvaliyle aynı yapın; ham capture card’ın üstüne yerleştirin. Browser Source’u OCR’nin okuduğu ham kaynağa dönüştürmeyin.
8. Canlı Çeviri’den başlatın. Windows katmanı isteğe bağlıdır ve seçili monitörü izler.

**HDMI passthrough üzerine PC yazılımı doğrudan çizim yapamaz.** Türkçe altyazı OBS kompozitinde, OBS projector çıkışında veya Windows monitör katmanında görülür. TV’ye OBS görüntüsü gönderilecekse bunun ayrıca bir PC görüntü çıkışı olduğu hesaba katılmalıdır.

## Yerel model: yalnız açıkça istediğinizde hazırlayın

Çalışan model: [Helsinki-NLP/opus-mt-tc-big-en-tr](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-tr), revizyon `e539fc16a8a1a0ea5950eb339b595bfcce990e90`, CC-BY-4.0. Bu görevde ağırlık, beam=4, tokenizasyon, çeviri sözlüğü ve bağlam mantığı değiştirilmedi.

Aşağıdaki komutlar **isteğe bağlı indirme** yapar; uygulama bunları kendiliğinden çalıştırmaz. Dönüştürme ortamını ana GUI ortamından ayrı tutun:

```powershell
py -3.12 -m venv .venv-convert
.\.venv-convert\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv-convert\Scripts\python.exe -m pip install -r requirements/convert.txt
.\.venv-convert\Scripts\python.exe tools/run.py prepare-light --allow-download --output models/opus-en-tr
py -3.12 -m venv .venv-nmt
.\.venv-nmt\Scripts\python.exe -m pip install -r requirements/light-tested.txt
```

Dönüştürme hedefi daha önce varsa üzerine yazılmaz. İndirilmiş `source` klasörüyle çevrimdışı dönüşüm için `--allow-download` yerine `--offline-convert` kullanın. Hazır `models/opus-en-tr/ct2-int8` klasöründe `model.bin`, `source.spm`, `target.spm`, `ediz_nmt.json` bulunmalıdır.

Bağlantılar’da motor `ct2-marian`, Python `.venv-nmt\Scripts\python.exe`, model `ct2-int8`, CPU için `int8` seçin. GPU için CUDA uyumlu NVIDIA sürücüsü ve CTranslate2’nin gerektirdiği kitaplıklar gerekir. Test edilen ayrı Windows ortamı: CT2 4.9.0, SentencePiece 0.2.3, cuBLAS 12.9.2.10, CUDA Runtime 12.9.79. İsteğe bağlı kurulum:

```powershell
.\.venv-nmt\Scripts\python.exe -m pip install nvidia-cublas-cu12==12.9.2.10 nvidia-cuda-runtime-cu12==12.9.79
```

CUDA için `cuda`, `int8_float16`, işçi=1, CPU iş parçacığı=2 seçin. Desteklenmeyen aygıt/eksik dosya açık hata verir; bulut fallback yapılmaz. Model oturum boyunca ayrı süreçte bir kez yüklenir ve sıcak kalır. Durdur/Kapat işlemi işçiyi kapatır; yükleme sürerken iptal edilebilir. `argos-ct2` yalnız mevcut uyumlu manifestli kurulumlar içindir; bu görevde yeni motor eklenmedi. [CTranslate2 donanım belgeleri](https://opennmt.net/CTranslate2/installation.html) ortamınıza göre kontrol edilmelidir.

## Arayüz

- **Canlı Çeviri:** başlat/durdur, oyun, doğrulanmış bağlantı, ham kare + gösterim önizlemesi, son EN/TR geçmişi, ölçülen süreler.
- **Altyazı Tasarımı:** örnek sahne, yazı boyutu, ayrı isim rengi/görünürlüğü, hizalama ve maske konumu/boyutu; seçili oyuna kaydetme. Sıfırla kaydedilmiş profile döner.
- **Oyun Profilleri:** ekle, seç, yeniden adlandır; oyun başına ayrı OCR ve maske ayarı. Aktif oturum sırasında profil değişimi engellenir.
- **Bağlantılar:** OBS, ham kaynak, model ve monitör. Gelişmiş seçenekler başlangıçta kapalıdır.
- **Tanılama:** OCR, son model işleme, kapasite beklemesi, gönderim→renderer ACK, aktif kaynak, kaynak kaybı→kaldırma ACK, günlük ve görünürlük zamanlarına dayalı SRT.

Ölçülmeyen süre `—` olur. Renderer ACK, browser DOM için iki animation frame sonrası yazılım raporudur; panel/TV pikselinin fiziksel görünme zamanı değildir. Son replik alanları geçmişi gösterir; gerçek altyazı katmanının görünürlüğünü belirlemez.

## Düzenlenmiş proje yapısı

```text
launcher.py / runtime_check.py / *.bat / EdizGameTranslator.spec
src/ediz_game_translator/
  app.py / core.py       uygulama ve ayar yönetimi
  ui/                   CustomTkinter, OCR bölge editörü
  capture/              ham yakalama, OCR, takip ve güvenlik
  translation/          ayrı yerel işçi, dispatch ve mevcut çeviri belleği
  subtitles/            canlı görünürlük, ortak maske, OBS/native çıkış
  storage/              SQLite, oyun ve altyazı profilleri
  benchmarks/           model hazırlama ve benchmark modülleri
  diagnostics/          izole paket doğrulaması
tests/                  otomatik regresyonlar ve sentetik girdiler
tools/benchmarks/       replay ve performans araçları
tools/smoke/             izole test/önizleme araçları
requirements/           runtime, kilit, build, dönüşüm ve yerel motor listeleri
examples/               gizli bilgi içermeyen örnekler
docs/reports/            Türkçe teknik raporlar
docs/images/             yalnız sentetik Windows ekran görüntüleri
models/                 yerel, gitignore
benchmark-private/      özel korpus, gitignore
dist/ / build/          derleme çıktısı, gitignore
```

Normal kullanıcı ayarları `%APPDATA%\EdizGameTranslator` altında tutulur (kesin yol için `core.config_folder`). `EDIZ_CONFIG_DIR` ile ayrı bir test profili kullanılabilir. OBS parolası kasa kaydıdır. Gerçek ayarlar, SQLite, SRT, oyun kayıtları, modeller, ortamlar ve EXE Git’e eklenmez. Eski çalışma klasörü ve CUDA ortamı otomatik temizlenmez; yerel envanter ve temizlik önerileri ayrı tutulur.

## Test, benchmark ve EXE

```powershell
.\.venv-win\Scripts\python.exe -m unittest discover -s tests
.\.venv-win\Scripts\python.exe tools/run.py preview_redesign --scale 1.25
.\.venv-nmt\Scripts\python.exe tools/run.py benchmark-light --model-path models/opus-en-tr/ct2-int8 --corpus benchmark-private/corpus.json --output benchmark-private/result.json --device cuda --compute-type int8_float16 --workers 1 --threads 2 --beam-size 4
```

`PAKETLE.bat` PyInstaller ile `dist/EdizGameTranslator/EdizGameTranslator.exe` üretir. Mevcut EXE’yi korumak için geliştirme doğrulamasında yeni `--distpath`/`--workpath` kullanıldı. Kaynaktaki `BASLAT.bat` ve dağıtım EXE’si aynı paket girişini kullanır.

Geliştirme raporu: [UI_LIVE_SYNC_RAPORU.md](docs/reports/UI_LIVE_SYNC_RAPORU.md). Tarihsel yerel model sonuçları: [PERFORMANS_YEREL.md](docs/reports/PERFORMANS_YEREL.md). PS5→TV gerçek uçtan uca doğrulama tamamlanmadan 500–800 ms başarı iddiası yapılmaz.
