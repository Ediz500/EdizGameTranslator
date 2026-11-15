# EdizGameTranslator

Windows üzerinde PS5/capture card görüntüsündeki İngilizce oyun diyaloglarını
OCR ile okuyup Türkçe altyazıya çeviren masaüstü uygulaması. Tkinter arayüzü,
OBS Browser Source çıktısı ve masaüstü overlay'i içerir. En fazla üç altyazı
aynı anda, birbirinden bağımsız okuma sayaçlarıyla gösterilir.

Bu depo kaynak kodlarını içerir. EXE, sanal ortam, model ağırlıkları, gerçek
kullanıcı ayarları, API anahtarları, oyun kayıtları ve yerel tanılama dosyaları
depoya dahil edilmez.

## Gereksinimler

- Windows x64 ve resmî **CPython 3.12 x64**. MSYS2 Python desteklenmez.
- OBS Studio, OBS WebSocket ve OBS Virtual Camera.
- DirectShow üzerinden OBS'ye görüntü veren bir HDMI capture card.
- Bulut çevirisi için internet, OpenAI hesabında seçilen modele erişim ve API
  anahtarı. Bu kullanım ücretlidir.
- OCR ana uygulamada CPU/ONNX Runtime üzerinde çalışır; CUDA zorunlu değildir.
  Yerel çeviri benchmark'ı için ayrı CUDA ortamı ve yeterli GPU belleği gerekir.

Python: [resmî indirme sayfası](https://www.python.org/downloads/windows/).
OBS: [resmî indirme sayfası](https://obsproject.com/download).

## Kurulum ve başlatma

Özel depoyu klonlamak için GitHub hesabınızın depoya erişimi olmalıdır:

```powershell
git clone https://github.com/Ediz500/EdizGameTranslator.git
cd EdizGameTranslator
.\KURULUM.bat
.\BASLAT.bat
```

`KURULUM.bat`, uyumlu Python'u denetler ve `.venv-win` içinde
`requirements.txt` bağımlılıklarını kurar. `requirements-win-lock.txt` kurulumun
sürüm kısıtlarını içerir. Mevcut uyumsuz sanal ortam otomatik silinmez.

Elle kurulum için:

```powershell
py -3.12 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-win\Scripts\python.exe -m pip check
.\BASLAT.bat
```

İlk kurulumda paketlerin ve gerekiyorsa OCR ağırlıklarının indirilmesi için
internet gerekir. Ana uygulamanın OCR modelini önceden hazırlamak için:

```powershell
.\.venv-win\Scripts\python.exe -c "from ocr_profiles import create_ocr; create_ocr('bounded960_cpu2'); print('OCR hazir')"
```

RapidOCR kendi sürümünün model yapılandırmasını kullanır. Ağırlık dosyalarını
bu depoya kopyalamayın. İnternetsiz OCR denemesini gerekli dosyalar kurulduktan
sonra yapın. Bulut çevirisi ayrıca internet gerektirir.

## PS5, capture card ve OBS bağlantısı

1. PS5 HDMI çıkışını capture card HDMI girişine bağlayın. Kartın USB bağlantısını
   bilgisayara, varsa HDMI passthrough çıkışını oyun ekranına bağlayın.
2. OBS'de **Video Capture Device / Video Yakalama Aygıtı** kaynağı oluşturun ve
   gerçek capture card'ı seçin. Örneğin kaynak adı `PS5 Raw Capture` olabilir.
3. OBS Virtual Camera ayarlarında **Source / Kaynak → filtresiz ham capture card
   kaynağını** seçin ve sanal kamerayı başlatın. Program, Scene veya Preview
   çıkışını OCR kaynağı olarak kullanmayın.
4. OBS WebSocket'i localhost üzerinde açın. Uygulamanın varsayılan bağlantı portu
   `4455`'tir. Gerekiyorsa OBS parolasını uygulamanın gelişmiş ayarlarında girin.
5. Uygulamada aynı ham kaynak adını seçin. OBS koleksiyonu otomatik bulunamazsa
   gelişmiş ayarlardan kendi koleksiyon dosyanızı belirtin.
6. Oyunu seçin ve **OCR Bölgesini Düzenle** ile İngilizce altyazının bulunduğu
   bölgeyi işaretleyin. İlk denemeyi **API'siz OCR tanılama** modunda yapın.
7. Kaynak doğrulandıktan sonra bulut çevirisini kullanmak istiyorsanız API
   anahtarını, modeli ve bütçeyi kendi hesabınıza göre yapılandırın.

OBS çıkışı yalnız güvenli, filtresiz ham kaynak olarak doğrulanırsa yakalama
başlar. Browser Source, OBS program görüntüsü veya overlay'i tekrar yakalayan
yönler reddedilir. Kaynak güvenliği kaybolursa akış durur; uygulama OBS yayın
sahnesini veya TV projektörünü kendiliğinden değiştirmez.

## Türkçe altyazıyı OBS'ye ekleme

OBS'de ayrı bir **Browser Source / Tarayıcı Kaynağı** oluşturun:

- Adres: `http://127.0.0.1:8788/overlay`
- Boyut: `1920 × 1080`
- Sayfa şeffaf arka planlıdır.

Bu kaynak yayın/izleme sahnesine eklenebilir. OCR'yi besleyen sanal kameraya geri
dönmemelidir. Masaüstü overlay'i uygulamadan ayrıca açılıp kapatılabilir.

## OCR ve altyazı kuyruğu

`LatestFrames` son ham kareyi paylaşır; eski kareleri biriktirerek OCR kuyruğu
oluşturmaz. `bounded960_cpu2` profili dedektör boyutunu sınırlar ve ONNX Runtime
CPU iş parçacıklarını kısıtlar. OCR bölgesi düzenleyicisi aktif yakalama ile aynı
kareyi ve OCR motorunu paylaşabilir.

`ActiveSubtitles`, konuşmacı ve konuma göre aktif diyalogları izler. Dar kapsamlı
OCR/noktalama onarımları karşılaştırmada kullanılır; isim, sayı, olumsuzluk ve
anlam değişimleri için korumalar vardır. Kısa gerçek tekrarlar ayrı ele alınır.
Ham gözlemler ve kanonik düzeltmeler yerel SQLite kaydında korunur.

Çeviri ve gösterim işleri SQLite FIFO'sunda tutulur. Yeni İngilizce satır veya
boş OCR karesi, okunmakta olan Türkçe altyazıyı hemen silmez. Üç bağımsız gösterim
alanı vardır; dördüncü iş bekler. Sayaç renderer bildiriminden sonra başlar.
Durdurma, kapanış ve kaynak güvenliği kaybı açık oturumun gösterimini iptal eder.

## Çeviri motorları

Ana GUI'nin mevcut seçenekleri:

| Seçenek | Model kimliği | Durum |
|---|---|---|
| GPT-6 Luna | `gpt-6-luna` | Varsayılan bulut motoru |
| GPT-6.1 Terra | `gpt-6.1-terra` | Bulut motoru |
| GPT-6.1 Sol | `gpt-6.1-sol` | Bulut motoru |

Model kimlikleri uygulamanın mevcut `model_config.py` sözleşmeleridir. Hesabınızın
model erişimini ayrıca kontrol edin. Uygulama önceki çevrilmiş replikleri ve
kullanıcının oyun notlarını bağlam olarak kullanır; yalnız yeni repliği çevirir.
Yerel bütçe defteri yaklaşık harcamayı izler; sağlayıcının kesin fatura sınırı
yerine geçmez. AI testi de gerçek API çağrısı yapar ve ücretlidir.

Yerel modeller şu anda **GUI seçeneği değil, ayrı benchmark altyapısıdır**.
Ölçülmüş bir yerel hız/kalite kazananı seçilmemiştir. 500–800 ms uçtan uca hedefi
henüz doğrulanmamıştır. Yerel model hatasında ücretli API'ye otomatik dönüş yoktur.

## İsteğe bağlı yerel çeviri modelleri

Bu adımlar yalnız yerel modelleri indirmek ve karşılaştırmak isteyenler içindir.
Ana `.venv-win` ortamını değiştirmeyin:

```powershell
py -3.12 -m venv .venv-local
```

[PyTorch resmî kurulum seçicisinden](https://pytorch.org/get-started/locally/)
Windows, Pip, Python ve sürücünüze uygun CUDA paketini seçin. Verilen kurulum
komutunu `.venv-local\Scripts\python.exe -m pip` ile çalıştırın; `torch` ve
`torchvision` kurulmuş olmalıdır. Ardından:

```powershell
.\.venv-local\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv-local\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"
```

Desteklenen çeviriye eğitilmiş checkpoint'ler:

| CLI anahtarı | Resmî model |
|---|---|
| `milmmt-1b` | [xiaomi-research/MiLMMT-46-1B-v1.0](https://huggingface.co/xiaomi-research/MiLMMT-46-1B-v1.0) |
| `milmmt-4b` | [xiaomi-research/MiLMMT-46-4B-v1.0](https://huggingface.co/xiaomi-research/MiLMMT-46-4B-v1.0) |
| `translategemma-4b` | [google/translategemma-4b-it](https://huggingface.co/google/translategemma-4b-it) |
| `translategemma-12b` | [google/translategemma-12b-it](https://huggingface.co/google/translategemma-12b-it), isteğe bağlı kapasite testi |

Pretrain modelleri kullanılmaz. Modelin lisans ve erişim koşullarını kendi
Hugging Face hesabınızla tamamlayın. Erişim gerektiren modeller için CLI'dan
`hf auth login` kullanabilirsiniz; token'ı kaynak dosyasına veya Git remote
adresine yazmayın.

İndirme açıkça istenir; uygulama açılışında otomatik yapılmaz:

```powershell
.\.venv-local\Scripts\python.exe local_benchmark.py download --allow-download --model milmmt-1b --path models\milmmt-1b
```

Diğer modeller için tablo anahtarını ve ayrı hedef klasörü kullanın. Araç resmî
repo commit'ine sabitlenir ve model/sürüm manifesti yazar. BF16 ağırlıklar indirilir;
NF4 dönüşümü yükleme sırasında yapılır. Gerçek VRAM gereksinimi ağırlık boyutuna
eşit değildir; OBS, OCR ve diğer süreçler de belleğe ihtiyaç duyar.

## Kendi kayıtlarınızla benchmark

Gerçek kullanıcı SQLite dosyası ve diyalog kümesi depoya konmamıştır. Önce kendi
OCR kayıtlarınızı oluşturun, sonra yerel veri kümesini çıkarın:

```powershell
.\.venv-win\Scripts\python.exe local_benchmark.py export --database "$env:APPDATA\EdizGameTranslator\subtitles.sqlite3" --limit 75 --output benchmark-private\corpus.json
.\.venv-local\Scripts\python.exe local_benchmark.py run --model milmmt-1b --path models\milmmt-1b --corpus benchmark-private\corpus.json --workload idle --output benchmark-private\milmmt-idle.json
```

En az 50 ayrı uygun replik gerekir. Araç kaynak SQLite dosyasını salt okunur
açar. Kayıtlı Luna yanıtları varsa referans alınır; bunlar kusursuz doğruluk
ölçütü değildir. Model tek alt süreçte yüklenip sıcak tutulur. Isınma örneği
yüzdeliklere katılmaz. Yükleme, tam yanıt p50/p95, kısa/uzun replikler, VRAM,
RAM, GPU/CPU yükü ve çalışma hataları ayrı kaydedilir.

OBS ve API'siz OCR çalışırken aynı deneyi ayrı dosyaya `--workload obs-ocr` ile
tekrarlayın. Etiket tek başına OBS/OCR'nin gerçekten aktif olduğunun kanıtı
değildir. TranslateGemma için bağlamlı deneme ayrıca `--experimental-context`
kullanır ve resmî şablon dışı deney olarak işaretlenir. MiLMMT resmî çeviri
istemini; bağlamsız TranslateGemma dil kodları içeren resmî chat template'i kullanır.

Kalite incelemesini ayrı yapın:

```powershell
.\.venv-win\Scripts\python.exe local_benchmark.py review --corpus benchmark-private\corpus.json --result benchmark-private\milmmt-idle.json --output benchmark-private\review.csv
.\.venv-win\Scripts\python.exe local_benchmark.py quality --review benchmark-private\review.csv --output benchmark-private\quality.json
```

CSV'de doğruluk/doğallık 1–5; isim, olumsuzluk, anlam kaybı, eksik çeviri ve fazla
metin alanları 0/1 ile doldurulur. Doldurulmamış inceleme sıfır hata sayılmaz.
Benchmark ağsız yerel dosya yükler; CUDA hatası veya zaman aşımı açık hata olur.

## Kullanıcı verileri ve örnek yapılandırma

- Anahtarlar Windows Kimlik Bilgisi Yöneticisi'nde saklanır.
- Gerçek ayarlar, harcama defteri, SQLite ve tanılama dosyaları
  `%APPDATA%\EdizGameTranslator` altında yereldir.
- `examples/settings.example.json` kişisel veri ve anahtar içermeyen ayar örneğidir.
  Mevcut ayarlarınızın üstüne otomatik kopyalamayın; ayarları GUI'den düzenleyin.
- `.env` ana uygulamanın zorunlu yapılandırma yöntemi değildir. Anahtarınızı
  Python dosyasına, örnek JSON'a veya README'ye yazmayın.
- Ham OCR kayıtları özel metin içerebilir. Bunları issue, commit veya ekran
  görüntüsüyle paylaşmadan önce ayrıca gözden geçirin.

Overlay HTML/CSS/JavaScript'i `overlay_view.py` içinde gömülüdür; bu bileşenin
çalışması için ayrı bir Node.js kurulumu veya frontend derlemesi gerekmez.

## Testler ve EXE oluşturma

```powershell
.\.venv-win\Scripts\python.exe -m unittest discover -s tests -v
.\.venv-win\Scripts\python.exe -m pip check
.\PAKETLE.bat
```

Otomatik testlerde ücretli OpenAI çağrıları taklit edilir. Windows GUI ve yerel
HTTP testleri masaüstü oturumu ve localhost erişimi gerektirir. Kamera/OBS ile
canlı smoke araçları ayrıca, isteğe bağlı çalıştırılır. Testlerdeki JSON dosyaları
sentetik/anonymize fixture'lardır; kişisel SQLite veya gerçek diyalog arşivi değildir.

Paketleme sonucu `dist\EdizGameTranslator\EdizGameTranslator.exe` oluşur.
EXE ve `_internal` dizini birlikte tutulmalıdır. Torch ve yerel çeviri ağırlıkları
ana EXE'ye eklenmez. Yeni klonda hazır EXE bulunmaz; kaynak çalıştırma için
`BASLAT.bat`, paket oluşturmak için `PAKETLE.bat` kullanılır.

## Depo kapsamı

Kaynaklar, testler, bağımlılık listeleri, BAT dosyaları, PyInstaller `.spec` ve
örnek yapılandırma sürümlenir. `.gitignore`; sanal ortamları, dağıtımları, model
ağırlıklarını, kullanıcı verilerini, yerel raporları ve büyük geçici dosyaları
dışarıda tutar. Yalnız `.gitignore` eklemek eski commit'teki dosyayı kaldırmaz:
GitHub için hazırlanan ilk snapshot, eski yerel geçmişi taşımayan temiz depodur.
Orijinal çalışma klasörü ve yerel geçmiş yedekte korunmuştur.

Bu özel deponun oluşturulması kodu otomatik olarak açık kaynak lisansına geçirmez.
Bağımlılıkların ve indirilen modellerin kendi lisans koşulları geçerlidir.
