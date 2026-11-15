# Yerel geliştirme ölçüm raporu — 15 Kasım 2026

Bu belge ölçüm anındaki sürümün tarihsel raporudur. API kodu artık
`archive/openai-api-legacy` dalında korunur; aktif yerel daldan kaldırılmıştır.
Güncel temizlik ve önce/sonra karşılaştırması [YEREL_TEMIZLIK_RAPORU.md](YEREL_TEMIZLIK_RAPORU.md)
dosyasındadır. Aşağıdaki ölçülmüş veriler değiştirilmedi.

| Model / çalışma biçimi | İlk süreç → sıcak hazır | Sıcak tam sonuç p50 / p95 | Türkçe kalite | VRAM | Hata oranı |
|---|---:|---:|---|---|---|
| OPUS-MT EN→TR, CT2 INT8 CPU, beam 4 | 980 ms | 129 / 334 ms | Kısa ifadeler kullanılabilir; uzun/deyimli repliklerde anlam kaybı | Model CPU'da; sistem GPU toplamı 1435 MiB civarı | Çalıştırma 0/177; kalite ölçülmedi |
| OPUS-MT EN→TR, CUDA INT8/FP16, beam 4 | 1391 ms | 49 / 109 ms | Beam 1'deki bir güç/sahiplik hatası düzeldi; diğer hatalar sürüyor | Sistem GPU tepe 1902 MiB; model tek başına ölçülmedi | Çalıştırma 0/177; kalite ölçülmedi |
| Aynı CUDA model + OBS açık + sürekli gerçek OCR | 1351 ms | 47 / 109 ms | Aynı model; kalite onayı değildir | Sistem GPU tepe 1898 MiB, en az 10218 MiB boş | Çalıştırma 0/177; OCR süreç hatası 0/112 çevrim |
| Argos doğrudan EN→TR 1.5 | Ölçülmedi | Ölçülmedi | İncelenmedi | Ölçülmedi | Ölçülmedi |
| NLLB-600M | Ölçülmedi | Ölçülmedi | İncelenmedi; CC-BY-NC-4.0 | Ölçülmedi | Ölçülmedi |
| MiLMMT 1B/4B, TranslateGemma 4B/12B | İndirilmedi | Ölçülmedi | Önceki benchmark korunur | Ölçülmedi | Ölçülmedi |

Bu tablo **modelin tam Türkçe sonucuna kadar geçen süreyi** gösterir. Capture,
OCR, kapasite beklemesi, gösterim kuyruğu, renderer veya fiziksel TV süresi dahil
değildir. İlk yükleme, dosya bütünlüğü + süreç açma + motor yükleme + bir ısınma
çevirisini kapsar; reboot sonrası gerçek disk cold-cache testi yapılmadı.
Çalıştırma hatasının sıfır olması çevirinin doğru olduğu anlamına gelmez.

## Deney koşulları ve seçim

Windows x64 / Python 3.12, RTX 3060 12 GB, sürücü 617.42, CTranslate2 4.9.0,
SentencePiece 0.2.3, psutil 7.2.2. Dönüşüm ayrı ortamda Transformers 4.57.6 ve
Torch 2.15.0+cpu ile yapıldı. Ana uygulama ortamına paket kurulmadı. Kullanıcı
OPUS indirme, dönüştürme ve ölçümünü açıkça onayladı. Ücretli API çağrısı yok.

Model: [Helsinki-NLP/opus-mt-tc-big-en-tr](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-tr),
revizyon `e539fc16a8a1a0ea5950eb339b595bfcce990e90`, doğrudan EN→TR, CC-BY-4.0.
Pretrain/LLM sohbet checkpoint'i kullanılmadı. Dönüşmüş model.bin yaklaşık
227 MiB. Manifest ve dosya hash'leri model klasöründe tutulur; ağırlıklar Git'e
alınmaz. Resmî SentencePiece kaynak/hedef tokenizasyonu kullanılır.

Veri: SQLite'tan önceden çıkarılmış 59 farklı OCR gözlemi × 3 tekrar = 177
çeviri. Kısa grup ≤60 karakter: 45 gözlem / 135 işlem; uzun: 14 / 42 işlem.
Bu **insan tarafından temizlenmiş 59 doğru replik** değildir. Sonunda `201S`
gürültüsü bulunan varyant gibi OCR kusurları vardır; bunlar uydurma cümlelerle
tamamlanmadı veya sessizce doğru kabul edilmedi. Corpus SHA-256:
`f2d99cf167e85e9cd728872e54ee68d35fe94318f56771bdbf28afc1888811d2`.
Kayıtlı 25 Luna referansı kalite inceleme CSV'sine eklenir; gold değildir.

CPU testi iki CT2 kapasitesi / iki intra-thread, seri istek; CUDA bir kapasite /
iki thread ile yapıldı. Kapasite ayarı throughput veya iki kat hız iddiası
değildir. Isınma çağrısı yüzdeliklere dahil edilmedi, cache kullanılmadı.
Arka planda OBS ve masaüstü süreçleri vardı; makinadaki bütün yük kontrol
edilemedi. Sonuçlar tek makinede küçük örneklem ölçümleridir.

Geliştirme için en iyi **ölçülmüş aday** CUDA OPUS-MT beam 4'tür. CPU alternatifi
hazırdır. Beam 1 CUDA 40/96 ms, kısa replik 35/70 ms idi; beam 4'ün küçük ek
maliyeti belirgin bir anlam hatasını azalttığı için kabul edildi. Argos daha iyi
veya kötü ilan edilmedi: paket indirilmedi ve çalıştırılmadı. NLLB yalnız
[resmî kartındaki](https://huggingface.co/facebook/nllb-200-distilled-600M) ticari
olmayan lisans koşullarıyla araştırma adayıdır. Windows CUDA çalıştırması
[resmî CT2 koşullarına](https://opennmt.net/CTranslate2/installation.html) dayanır.

## Kısa ve uzun replikler

| Koşul (beam 4) | Kısa p50 / p95 / max | Uzun p50 / p95 / max | Tüm replik max |
|---|---:|---:|---:|
| CPU | 118 / 214 / 252 ms | 292 / 365 / 389 ms | 389 ms |
| CUDA | 42 / 81 / 109 ms | 95 / 134 / 147 ms | 147 ms |
| CUDA + OBS + sentetik OCR | 41 / 68 / 83 ms | 90 / 133 / 141 ms | 141 ms |

Yük testinin küçük farkları bir hızlanma kanıtı değildir. 112 gerçek RapidOCR
çevrimi üretildi; OBS süreci açık olduğu doğrulandı. OBS'nin kayıt/encoding veya
gerçek PS5 sahne yükü ayrıca doğrulanmadı. İşçi süreç ağacının RAM tepesi CUDA'da
785 MiB, CPU'da 305 MiB. Yük altında sistem RAM tepesi 17890 MiB, sistem CPU
p50/p95 %58.3/%74.4, GPU %57/%60 idi. CUDA işçisinin CPU kullanımı yaklaşık bir
çekirdektir; CPU işçisi yaklaşık 2.7 çekirdek kullanır. GPU toplamı OBS ve diğer
süreçleri içerir; yaklaşık 1435→1898 MiB farkı kontrollü tek-model VRAM tahsisi
değildir. 250 ms + nvidia-smi süresinde örnekleme kısa tepeleri kaçırabilir.

Windows venv python.exe başlatıcısının küçük RAM değeri model RAM'i sanılmasın
diye kaynak ölçümü çocuk süreçleri de toplar. Önceki pilot raporlardaki yalnız
başlatıcı RSS değeri kullanılmadı.

## OCR ve gösterim karşılaştırması

Aynı oluşturulmuş 960×160 görüntü zaman çizelgesinde 12 replik, 250 ms görünme,
100 ms boşluk, Arial 32; gerçek RapidOCR `bounded960_cpu2`. Dedektör ve metin
tanıyıcı önce yazılı karelerle ısıtıldı. Tek geçiş sonuçları:

| Tarama | Yakalanan / beklenen | Kayıp | Sahte kabul / tekrar | Görünme → kabul p50 / p95 / max | OCR çağrısı | CPU zamanı |
|---|---:|---:|---:|---:|---:|---:|
| Sabit 280 ms | 9/12 | 3 | 0 / 0 | 185 / 246 / 246 ms | 17 | 2.41 sn |
| Sabit hızlı 40 ms hedef | 12/12 | 0 | 0 / 0 | 76 / 97 / 97 ms | 93 | 12.05 sn |
| Adaptif 20 ms kontrol + 150 ms zorunlu OCR | 12/12 | 0 | 0 / 0 | 65 / 72 / 72 ms | 39 | 5.58 sn |

Bu, sentetik kısa replik testidir; gerçek görüntü kalitesi/arka plan/sıkıştırma
çeşitliliğini veya insan etiketli oyun recall'ını kanıtlamaz. Adaptif algoritma
metin ayrımına özgü değildir; hareketli oyun arka planı çok OCR tetikleyebilir.
Bu nedenle gerçek oyun etiketlemesine kadar sabit hızlı mod varsayılandır.

Gerçek Chromium tarayıcıda 20'şer sentetik çeviriyle hazır → iki requestAnimationFrame
sonrası DOM-ACK ölçümü: polling p50/p95/max **78/109/109 ms**, SSE
**16/16/31 ms**; eksik ACK yok. Örneklem küçüktür, Windows zaman çözünürlüğü
etkilidir. SSE bu ölçüm nedeniyle varsayılan yapıldı; polling fallback korunur.
Bu testte OCR/model yoktur. Fiziksel TV görünmesi ayrıca ölçülmelidir.

Gerçek OBS güvenlik maliyeti denemesi mevcut kaynak doğrulamasında
`CaptureConfigurationError` ile durdu; geçerli kare maliyeti **ölçülmedi**.
Güvenlik gevşetilmedi, OBS ayarı değiştirilmedi. Test fixture'larında değişmeyen
JSON bir kez ayrıştırılır; canlı yön/WebSocket kontrolü her ön/son kontrolde
çalışır ve bir sonraki başarısızlıkta akış durur. Her gerçek karede bu maliyetler
`capture_stages` ile ayrı kaydedilir.

## Doğruluk, testler ve sınırlamalar

Başlangıç 167 test geçti. Son regresyon paketi 195 test geçti. Özel testler:

- OCR çıktısı → filtre → CaptureRunner → SQLite hattında Go/No/Oh/Hi,
  Thank You, unvanlı/MJ konuşmacılar, aynı karede birden fazla konuşmacı,
  HUD/gürültü, düşük güven onayı, OCR varyantı, genişleyen cümle, Go→Stop→Go.
- İki bağımsız çeviri ters sırada tamamlandığında hazır sonuç eski eksik işi
  beklemez. Aynı repliğin revizyonları eşzamanlı çevrilmez. Üç blok ve ayrı
  sayaçlar, bekleyen dördüncü iş, oturum/generation iptalleri korunur.
- Tarayıcı bağlıyken native ACK sayacı erken başlatmaz. Güncelleme diğer blok
  sürelerini sıfırlamaz. SSE, kaynak origin kısıtları ve polling yolu test edilir.
- Model yokluğu, süreç zaman aşımı, out-of-order süreç cevapları ve kapanış;
  ücretli SDK çağrısı yasaklanarak test edilir. Kaynak bağlantı kaybı fail-closed
  davranışı mevcut testlerle korunur. Ayrı profil tarihsel ayar/defteri korur.
- Gerçek OCR + gerçek CUDA çeviri + Tkinter GUI sentetik smoke testi geçti:
  `MJ: We should leave now.` → `Artık gitmeliyiz.`, hata yok, API çağrısı 0.
- Temiz klasörden derlenmiş Windows EXE testi geçti: gerçek OCR, bölge
  düzenleyicisi, tek kamera açılışı, üç blok + bekleyen dördüncü iş ve HTTP ACK.
  EXE'nin dış Python işçisi CUDA/beam 4 ile olumsuz kapı talimatını
  `Kapıyı açmamalısın.` olarak çevirdi; işçi kapandı, GUI hatası/API çağrısı yok.
  Eski paket önbelleği nedeniyle ilk derlemede eski test modülü kaldığı saptandı;
  son paket `--clean` ve ayrı build/dist klasörleriyle oluşturulup doğrulandı.

Kalite CSV'si hazırlanmıştır: doğruluk/doğallık, isim, olumsuzluk, anlam kaybı,
eksik çeviri ve fazla metin alanları insan tarafından doldurulmalıdır. Henüz
insan puanlaması yok; kalite hata oranı `null`dur. Nitel incelemede:

- Kısa olumsuz kapı talimatı doğru korunuyor; MJ/Peter/Miles gibi isimler
  örneklerde korunuyor. Bu bütün corpus için ölçülmüş isim başarı oranı değildir.
- Beam 1 güç/sahiplik anlamını bozarken beam 4 ilgili örneği düzeltti.
- `controlling interest` hatalı biçimde ilgi olarak çevriliyor; iş görüşmesi
  `interview` sözcüğünde yanlış anlam seçiliyor; bazı çok cümleli repliklerde
  belirsizlik/son parça düşüyor. Deyim ve mutfak şakası doğal değil. Grup/karakter
  terimleri tutarsız; `Corrupt?` gibi bağımsız sözcük düşebiliyor.

Bu yüzden modeli kalite açısından tamamlanmış üretim sürümü ilan etmiyoruz.
İnsan etiketli ≥%98 yakalama, gerçek oyunda sıfır yanlış tekrar, fiziksel PS5
uçtan uca p50<250/p95<500 ms hedefleri **henüz doğrulanmadı**. Ayrı aşamaların
p50/p95 değerlerini toplayarak uçtan uca başarı iddiası yapılmadı. Luna'nın eski
4–6 saniyelik ilk istek nedenini yeni ücretli çağrıyla test etmedik; tek bir
nedene bağlamadık. Eski API kuyruğu/çağrı ayrımlı ölçüm altyapısı korunur.

## Dosyalar ve gerçek PS5 testi

OCR: `dialogue_filter.py`, `subtitle_tracking.py`, `capture_pipeline.py`,
`image_change.py`, `virtual_camera.py`, `frame_sources.py`.
Yerel yol: `light_translation.py`, `translation_dispatch.py`,
`translation_memory.py`, `prepare_light_model.py`, `benchmark_light.py`.
Gösterim: `subtitle_store.py`, `subtitle_display.py`, `overlay_server.py`,
`overlay_view.py`; GUI/başlatma: `app.py`, `app_ui.py`, `core.py`, `launcher.py`,
`package_checks.py`, `EdizGameTranslator.spec`; örnekler/bağımlılıklar/README
ve ilgili `tests/test_*` / `tests/benchmark_*` dosyaları. Büyük model altyapısı
silinmedi; yalnız kaynak ölçümünde süreç ağacı düzeltmesi yapıldı.

Geliştirme dalı `codex/low-latency-local`, temiz kaynak snapshot'ından ayrı
worktree'dir. GitHub main ve orijinal uygulama kaynakları/EXE üzerine yazılmadı.
Yerel snapshot'ın commit geçmişi GitHub'ın tarayıcı yükleme geçmişiyle aynı
değildir; bu dal GitHub'a itilmiş veya PR açılmış sayılmaz.

Deneme sırası:

1. Ayrı geliştirme başlatıcısını açın; çalışan eski uygulama 8788'i kullanıyorsa
   deneme öncesi onu normal arayüzünden kapatın. Ayarlar yeni özel profildedir.
2. OBS Virtual Camera çıkışını **Source → filtresiz ham capture card** olarak
   doğrulayın; program/scene/preview yönünü kullanmayın. Güvenlik reddediyorsa
   geçmeden önce nedeni düzeltin. OCR bölgesini gerçek İngilizce yazıya göre seçin.
3. CUDA / int8_float16 / işçi 1 / thread 2 ve hazırlanmış model yollarını kontrol
   edin; önce API'siz OCR tanılama, sonra yerel çeviri testi yapın.
4. Aynı PS5 videosunu 280 ms, sabit hızlı ve adaptif modlarda etiketleyin: ilk
   İngilizce görünme kareleri, gerçek ayrı replikler, isimler, tekrarlar. ≥50–100
   gerçek replik ve farklı sahnelerle recall/false-duplicate oranını çıkarın.
5. Kaydın monotonic frame/OCR/kabul/motor/kapasite/transport/DOM-ACK zamanlarını
   eşleştirin; TV için harici yüksek hızlı kamera ile İngilizce ve Türkçe ilk
   görünmeyi aynı çekimde ölçün. OBS encoding açık/kapalı sonuçlarını ayırın.
6. Kalite CSV'sini Luna referanslarını kusursuz kabul etmeden insan değerlendirsin.
   Bu ölçümler geçmeden ana sürümü değiştirmeyin.

Ham raporlar, corpus, CSV, kullanıcı profili ve modeller yerel `.test-tmp` / özel
benchmark klasörlerindedir; Git'e eklenmez. İzlenen belgede yalnız toplu ölçümler
vardır. Model indirme izni diğer büyük model veya Argos indirmesine genişletilmedi.
