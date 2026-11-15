# EdizGameTranslator

Bu dal **düşük gecikmeli yerel geliştirme sürümüdür**. Canlı yol internet veya
ücretli API kullanmaz. Ana sürümden ayrı profil ile denenmelidir. Gerçek PS5
uçtan uca hedefleri henüz doğrulanmadı; ölçümler ve sınırlamalar
[PERFORMANS_YEREL.md](PERFORMANS_YEREL.md) dosyasındadır.

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
- Canlı çeviri için ayrı Python ortamında CTranslate2 ve önceden hazırlanmış
  doğrudan EN→TR model dosyaları. Model yoksa açık hata gösterilir.
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
sonra yapın. Yerel çeviri de ağırlıklar hazırlandıktan sonra ağsız çalışır.

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
7. Kaynak doğrulandıktan sonra yerel Python yolunu, model klasörünü ve CPU/CUDA
   aygıtını seçin. CUDA için eşzamanlılığı 1 ve hesaplamayı `int8_float16` yapın.

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

SQLite işlerin kalıcı günlüğüdür. Sınırlı sayıda işçi bağımsız replikleri işler;
aynı repliğin revizyonları eşzamanlı çevrilmez. Hazır sonuçlar, önceki eksik
işi beklemeden üç gösterim alanından boş olana alınır. Yeni İngilizce satır veya
boş OCR karesi, okunmakta olan Türkçe altyazıyı hemen silmez. Üç bağımsız gösterim
alanı vardır; dördüncü iş bekler. Sayaç renderer bildiriminden sonra başlar.
Durdurma, kapanış ve kaynak güvenliği kaybı açık oturumun gösterimini iptal eder.
Kısa `Go!`, `No!`, `Oh!`, `Hi!` ve `Thank You` gerçek OCR filtre hattında korunur.
`Mr. Fisk`, `Dr. Connors`, `MJ` konuşmacı sınırları ayrıca test edilir.

Varsayılan OCR aralığı 40 ms hedeflidir; gerçek OCR maliyeti daha yüksekse eski
kare kuyruğu oluşturulmaz. İsteğe bağlı adaptif mod, ROI farkını 20 ms hedefle
kontrol eder ve 150 ms içinde zorunlu OCR taraması yapar. Gerçek oyun recall'ı
etiketlenene kadar varsayılan sabit hızlı moddur. OBS canlı yön, kaynak/filtre
ve sanal kamera kontrolleri her kare öncesi ve sonrası korunur. Değişmeyen
koleksiyon dosyasının JSON ayrıştırması stat imzasıyla yeniden kullanılır.

Overlay adresi değişmez. SSE varsayılandır; bağlantı hatasında 100 ms polling'e
döner. Tarayıcı bağlıyken masaüstü onayı sayacı erken başlatmaz. Her bloğun
sayacı bağımsızdır; DOM onayı fiziksel TV görünme kanıtı değildir.

## Canlı yerel çeviri motoru

Ölçülen aday [OPUS-MT EN→TR](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-tr),
CC-BY-4.0 lisanslı doğrudan çeviri modelidir. CTranslate2 INT8 dönüşümü CPU'da
ve RTX 3060'da çalıştırıldı. Ağırlık yaklaşık 227 MiB; indirme kaynağı yaklaşık
470 MB'dir. Konuşmacı etiketi modelden ayrılarak saklanır. Beam 4, belirgin bir
anlam hatasını beam 1'e göre düzelttiği için geliştirme varsayılanıdır; uzun ve
deyimli repliklerde hâlâ anlam kaybı vardır. Kalite onayı verilmiş ürün değildir.

GUI, ayrı Python alt sürecini oturum başında bir kez yükler ve sıcak tutar.
CPU'da 1–4 işçi, GPU'da bu sürümde 1 işçi sınırı vardır; toplam CPU thread sınırı
kontrol edilir. Süre aşımı/çökme açık hata verir, otomatik bulut dönüşü yoktur.
Luna/Terra/Sol kaynak kodu ve SDK sözleşme testleri tarihsel uyumluluk için
korunur; canlı yol ve GUI test düğmesi yerel motor kullanır. Anahtar ve geçmiş
bütçe kayıtları bu çalışma için değiştirilmez, yeni API ücreti oluşturulmaz.

Model indirmek tamamen isteğe bağlı ve açık bir CLI işlemidir. Ana uygulama
ortamından ayrı ortam oluşturun:

```powershell
py -3.12 -m venv .venv-nmt
.\.venv-nmt\Scripts\python.exe -m pip install -r requirements-light.txt
# Tek seferlik dönüşüm için (yalnız ağırlıkları indirmeyi seçtiyseniz):
.\.venv-nmt\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv-nmt\Scripts\python.exe -m pip install -r requirements-convert.txt
.\.venv-nmt\Scripts\python.exe prepare_light_model.py --allow-download --output models\opus-en-tr
```

GUI'de Python olarak `.venv-nmt\Scripts\python.exe`, model olarak
`models\opus-en-tr\ct2-int8` klasörünün tam yolunu seçin. Çalıştırma için Torch
gerekmemektedir; hazır model taşındığında `requirements-light.txt` yeterlidir.
Manifest sabit model revizyonu ve dosya SHA-256 değerlerini denetler. Marian
encoder-decoder modeli chat promptu kullanmaz; kaynak SentencePiece + EOS
tokenlarıyla çalışır. MiLMMT/TranslateGemma şablonlarıyla karıştırılmamalıdır.

CUDA için [resmî CTranslate2 kurulum koşulları](https://opennmt.net/CTranslate2/installation.html)
geçerlidir: Windows x64, uygun NVIDIA sürücüsü, CUDA 12 ve Visual C++ runtime.
Bu bilgisayarda sistem CUDA'sına dokunmadan ayrı ortamda aşağıdaki NVIDIA
paketleriyle doğrulandı; bunlar ek ve büyük indirmelerdir:

```powershell
.\.venv-nmt\Scripts\python.exe -m pip install nvidia-cublas-cu12==12.9.2.10 nvidia-cuda-runtime-cu12==12.9.79
```

İşçi yalnız kendi sürecinde DLL arama yolunu ayarlar. Aygıt `cuda`, hesaplama
`int8_float16`, işçi `1`, thread `2` seçin. CPU için `cpu`, `int8`, işçi `2`,
thread `2` başlangıç ayarıdır. Model ve bağımlılıklar kurulduktan sonra çevrimdışı
test edin. İlk yerel test ve ilk OCR çağrısı ısınma süresi içerir.

Argos'un [resmî paket dizininde](https://github.com/argosopentech/argospm-index)
doğrudan EN→TR 1.5 paketi bulunur; bu çalışmada indirilmedi/ölçülmedi. GUI'deki
`argos-ct2` manifest türü hazır, doğrulanmış CT2 paketi içindir; ham `.argosmodel`
dosyasını otomatik kuran bir yol bulunmaz. Henüz hazır kurulum adayı sayılmamalıdır.
[NLLB-600M](https://huggingface.co/facebook/nllb-200-distilled-600M) CC-BY-NC-4.0
lisanslıdır; ticari olmayan koşulları nedeniyle yalnız araştırma adayıdır ve
burada indirilmedi. CouchSubs oyun paketi yaklaşımı incelendi; AGPL kaynak kodu
kopyalanmadı. Basit, özgün lookup sırası: incelenmiş oyun paketi → aynı oyun,
konuşmacı ve önceki iki kaynak replikle eşleşen bellek → yerel model. Üç kelime
ve altı kısa ifadeler otomatik belleğe alınmaz; hazır pakette açık bağlam gerekir.

### Ayrı geliştirme profili

Çalışan sürümün ayar/SQLite/harcama dosyalarına dokunmadan denemek için boş bir
klasör seçin. Ortam değişkeni yalnız başlattığınız süreç ve çocukları için geçer:

```powershell
$env:EDIZ_CONFIG_DIR = "$PWD\benchmark-private\development-profile"
.\BASLAT.bat
```

Bu profil gerçek OBS kaynak adınızı ve yerel model yollarınızı GUI'den ayrı
girmeyi gerektirir; mevcut ayarlar üzerine örnek JSON kopyalamayın.

### Hafif model benchmark

```powershell
.\.venv-nmt\Scripts\python.exe benchmark_light.py --model-path models\opus-en-tr\ct2-int8 --corpus benchmark-private\corpus.json --device cpu --workers 2 --threads 2 --beam-size 4 --output benchmark-private\opus-cpu.json
# CUDA için: --device cuda --compute-type int8_float16 --workers 1
```

`--parallel` sabit kapasitede eşzamanlı yük denemesidir. Süreler tam çeviri
sonucuna kadardır, ilk token süresi değildir. Kalite hata oranı insan incelemesi
olmadan `null` kalır. Kaynak corpus, kaynak/çeviri metinleri ve ham raporlar özel
kalır. `tests/benchmark_image_schedule.py` sentetik görüntü üzerinde gerçek OCR;
`tests/benchmark_local_pressure.py` OBS açıkken sürekli sentetik OCR + gerçek
CUDA modeli; `tests/benchmark_browser_transport.py` gerçek tarayıcı DOM-ACK
karşılaştırmasıdır. Bunların hiçbiri gerçek PS5/TV uçtan uca testi değildir.

## Korunan büyük model benchmark'ı

Bu önceki altyapı korunur; bu görevde büyük modeller indirilmedi/ölçülmedi.
Bu adımlar yalnız modelleri indirmek ve karşılaştırmak isteyenler içindir.
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

İsteğe bağlı paket testi gerçek modele kadar genişletilebilir; `--self-test`
sentetik kamera ve geçici ayarlar kullanır, OBS'yi değiştirmez:

```powershell
.\dist\EdizGameTranslator\EdizGameTranslator.exe --self-test --report benchmark-private\package.json --local-python "$PWD\.venv-nmt\Scripts\python.exe" --local-model "$PWD\models\opus-en-tr\ct2-int8" --local-device cuda
```

## Depo kapsamı

Kaynaklar, testler, bağımlılık listeleri, BAT dosyaları, PyInstaller `.spec` ve
örnek yapılandırma sürümlenir. `.gitignore`; sanal ortamları, dağıtımları, model
ağırlıklarını, kullanıcı verilerini, yerel raporları ve büyük geçici dosyaları
dışarıda tutar. Yalnız `.gitignore` eklemek eski commit'teki dosyayı kaldırmaz:
GitHub için hazırlanan ilk snapshot, eski yerel geçmişi taşımayan temiz depodur.
Orijinal çalışma klasörü ve yerel geçmiş yedekte korunmuştur.

Bu özel deponun oluşturulması kodu otomatik olarak açık kaynak lisansına geçirmez.
Bağımlılıkların ve indirilen modellerin kendi lisans koşulları geçerlidir.
