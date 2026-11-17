# Ediz Game Translator — proje durumu

Güncelleme: **17 Kasım 2026**. Bu görev mevcut geliştirmeleri güvenli yayımlama ve dosya düzenini açıklama görevidir. Yeni model, bağımlılık, uygulama özelliği veya flicker düzeltmesi yapılmadı.

## Gerçek kullanım durumu

**Flicker çözülmüş değildir.** Son kullanıcı PS5 / Marvel's Spider-Man testinde:

- Bazı İngilizce replikler hâlâ ekrandayken Türkçe altyazı kaybolup yeniden geliyor.
- İngilizce replikler zaman zaman maskesiz görünüyor.
- Aynı konuşma için farklı çeviriler ve gereksiz çeviri işleri oluşabiliyor.
- 255/255 otomatik test geçmesi, gerçek PS5 davranışının yeterince kararlı olduğunu göstermiyor.

Kompakt siyah maske, metin konum sabitliği ve Türkçe çeviri kullanıcı testinde başarılıydı; OBS bağlantı koruması önceki testte başarılı bildirilmişti. Bunlar flicker'ın çözüldüğü anlamına gelmez. Ham oyun videosunun çevrimdışı OCR tekrarı Türkçe overlay içermez; özgün DOM görünürlük anlarını doğrudan kanıtlamaz. Önceki raporlardaki sentetik başarılar bu sınırlamayla okunmalıdır.

## Tek normal başlatıcı

Yerel ana klasörde **`EDIZ_BASLAT.bat`** kullanın. Açtığı sürüm:

- EXE: `dist/visual-stabilization-20261118/EdizGameTranslator/EdizGameTranslator.exe`
- Kaynak commit: `a5572cb057629dbc6eedad2b73eb61498e5dfc9e`
- Mevcut profil: `local-data/visual-stabilization-profile`
- EXE SHA-256: `32955e509d31c1c108ea2b1b004bc1e800190ac75124ceb980384f124f097c59`

Klasördeki `20261118` mevcut paket adıdır; bu görevde yeniden adlandırılmadı. Bu sürüm gerçek PS5'te denenmiş görsel stabilizasyon sürümüdür ve yukarıdaki sorunlar devam eder. Flicker denemesi varsayılan değildir. Başlatıcı mevcut EXE/profil yoksa hata verir; yeni ayar üretmez, model indirmez, başka sürüme sessizce geçmez. Normal açılışta uygulamanın kendi ayar/kayıt yazımı devam edebilir.

Önce açık çeviri uygulamasını kapatın; aynı anda iki sürüm 8788 portunu paylaşamaz. OBS Browser Source URL'si `http://127.0.0.1:8788/overlay`; sürüm değiştirince mevcut sayfayı yenileyin. Ham OBS kaynağı, model ve OCR ayarlarını değiştirmeyin.

Bu başlatıcı hazırlanmış **yerel EXE kurulumuna** yöneliktir. Temiz GitHub klonunda EXE, model ve kişisel profil bulunmaz; kaynak kurulumu için [README](README.md) ve mevcut `KURULUM.bat` / `BASLAT.bat` talimatlarını kullanın.

## Sürümler ve geri dönüş

| Sürüm / dal | Kaynak commit | Yerel kaynak | Paket / başlatıcı | Durum |
|---|---|---|---|---|
| UI canlı senkron | `b0f6c92` | `projects/ui-live-sync-redesign` | `dist/ui-live-sync-redesign` / `YENI_ARAYUZ_BASLAT.bat` | PR #3 başlığı; önceki sürüm |
| Yayın öncesi stabilizasyon | `3052c60` | `projects/prebroadcast-stabilization` | `dist/prebroadcast-stabilization-20261118` / `STABILIZASYON_TEST_BASLAT.bat` | Geri dönüş için saklanır |
| Görsel stabilizasyon | `a5572cb` | `projects/visual-stabilization` | `dist/visual-stabilization-20261118` / `EDIZ_BASLAT.bat` | Normal kullanım tercihi; bilinen sorunlar var |
| Flicker denemesi | `0f95352` | `projects/subtitle-flicker-fix` | `dist/subtitle-flicker-fix-20261117` / `FLICKER_TEST_BASLAT.bat` | 255 test geçti; gerçek PS5 testi yeterli kararlılığı doğrulamadı |

Son dalın sonraki belge/başlatıcı commit'leri `0f95352` kaynak davranışını değiştirmez. Flicker deneme EXE'si son kaynak dalının başarılı günlük sürümü olarak sunulmaz. Önceki `GORSEL_STABILIZASYON_BASLAT.bat` da aynı görsel sürümü açmaya devam eder.

Geri dönüşte açık uygulamayı kapatın, tabloda belirtilen önceki BAT'ı açın ve OBS sayfasını yenileyin. EXE, `_internal` klasörü veya profilleri birbirinin üzerine kopyalamayın.

## Git geçmişi ve güvenli aktarım

Doğrulanan doğrusal zincir:

```text
codex/ui-live-sync-redesign       b0f6c92
  -> codex/prebroadcast-stabilization 3052c60
  -> codex/visual-stabilization       a5572cb
  -> codex/subtitle-flicker-fix       0f95352
  -> bu aktarımın belge/başlatıcı commit'leri
```

Her önceki dal için `git merge-base --is-ancestor <dal> HEAD` başarılıdır. Geçmiş yeniden yazılmaz; squash, force-push ve otomatik merge yapılmaz. Yalnız `codex/subtitle-flicker-fix` gönderilir. Yeni Draft PR'ın tabanı `codex/ui-live-sync-redesign`; `main` ve [PR #3](https://github.com/Ediz500/EdizGameTranslator/pull/3) değiştirilmez.

Ana klasörde ayrıca eski, bağımsız `master` deposu (`ea7a7be`) ve commitlenmemiş dosyalar vardır. Bu eski kök çalışma kopyası yeni `src/` düzeninin üzerine kopyalanmadı. İki deponun Git bundle'ları, çalışma ağaçlarının patch'leri ve eski kaynak ZIP'i **yalnız yerel özel yedekte** korunur. Eski bağımsız geçmişi son dala zorla birleştirmek gereksiz çatışma ve özel veri riski taşır. GitHub'daki eski API arşivi ayrıca korunur.

Gönderilecek dalın tüm erişilebilir commit/blob geçmişi anahtar/parola, kişisel yol, yasak dosya ve büyük nesne açısından taranır. Testlerdeki sahte parolalar ile standart GitHub noreply commit adresleri gerçek kullanıcı sırrı değildir. `tests/spiderman_display_timing.json` yalnız önceden anonimleştirilmiş sayısal zamanları; diğer JSON fixture'ları sentetik test örneklerini içerir. Gerçek OCR metinleri/SQLite veya oyun videosu değildir. `docs/images` içindeki mevcut görseller sentetik arayüz/maske testleridir.

## Dosya envanteri ve kesinlikle korunacaklar

[Envanter ve sınıflandırma](docs/reports/PROJE_ENVANTERI.md). Yerel tam dosya listesi ve özel yedek dizini: `.test-tmp/github-transfer-20261117/`. Bu özel dizin GitHub'a gönderilmez.

**`.test-tmp` topluca silinmemelidir:** çalışan model ve çeviri Python ortamı burada bulunur. Mevcut profillerin doğrulanmış başvuruları:

- `.test-tmp/local-nmt-env/Scripts/python.exe`
- `.test-tmp/local-models/opus-en-tr/ct2-int8`

Tüm `.venv*`, `.test-tmp/local-only-env`, `.test-tmp/ui-redesign-env`, NVIDIA/CUDA DLL'leri, model/tokenizer dosyaları, `dist` içindeki bütün paket klasörleri, `projects` worktree'leri ve ortak `.git` dizinleri korunur. `local-data` ve ana klasördeki özel SQLite/OCR/benchmark kayıtları da korunur. OBS parolaları Windows kimlik kasasındadır; dışa aktarılmaz veya değiştirilmez.

Kök `BASLAT.bat` eski kök Python kopyasını açar; yeni normal kullanım tercihi `EDIZ_BASLAT.bat`tır. Diğer BAT'lar doğrulanmadan taşınmaz; birçoğu `%~dp0` ile kendi konumuna bağlı çalışır. Worktree'nin `.git` dosyası ortak Git deposuna işaret eder; Explorer ile klasör taşımak bağlantıları bozabilir.

## Önerilen sade düzen — taşıma uygulanmadı

İlk aşama şimdi tamamlanır: tek normal giriş `EDIZ_BASLAT.bat`, tek durum belgesi, eski yolların korunması. Hedef kullanıcı görünümü:

```text
EdizGameTranslator/
  EDIZ_BASLAT.bat          # normal kullanım: görsel stabilizasyon
  PROJE_DURUMU.md          # sürümler, bilinen sorunlar, geri dönüş
  dist/                   # mevcut EXE paketleri; değişmeden korunur
  projects/               # mevcut Git worktree'leri; değişmeden korunur
  local-data/             # özel profiller/veritabanları; Git dışında
  .test-tmp/              # çalışan model/ortamlar + yerel test arşivi
  arsiv/                  # ileride ONAYLA düzenlenecek rapor/başlatıcı indeksi
```

**Onay bekleyen sonraki aşama:** kökteki eski raporlar için `arsiv/raporlar`, önceki sürümlere açıklamalı erişim için `arsiv/geri-donusler` önerilir. Önce dosya bazında liste/hash ve BAT göreli yolları doğrulanmalı; taşınacak BAT'ların yeni konumu için başlatma yolu yeniden denenmelidir. Model/venv mutlak yollarını ve worktree metadata'sını etkileyen taşıma bu planın dışında tutulur. `build` çıktıları ve indirme önbelleği ancak bağımlılık/geri dönüş denetiminden sonra aday olabilir. Aynı EXE hash'i, bütün paket klasörünün gereksiz olduğunu kanıtlamaz. **Bu görevde taşıma veya silme yapılmadı.**

## Claude Code bağımsız incelemesi

Depo: [Ediz500/EdizGameTranslator](https://github.com/Ediz500/EdizGameTranslator).
İnceleme dalı: [codex/subtitle-flicker-fix](https://github.com/Ediz500/EdizGameTranslator/tree/codex/subtitle-flicker-fix).
Karşılaştırma tabanı: `codex/ui-live-sync-redesign`. Yeni Draft PR bağlantısı teslim raporunda verilir; PR birleştirilmez.

Önce bu belgeyi ve [önceki flicker kanıtının sınırlarını](docs/reports/ALTYAZI_FLICKER.md) okuyun. İnceleme odağı: OCR/track yaşam döngüsü, `live_sources`, tekrar iş üretimi, geç sonuçlar, boş sunucu snapshot'ları, browser DOM güncellemeleri ve maske güncelliği. Testlerden geçen varsayımların gerçek PS5 görüntüsünü neden karşılamadığını bağımsız değerlendirin; sentetik başarıyı çözüm kabul etmeyin.

Windows ve hazır bağımlılıklarla test komutu: `python -m unittest discover -s tests -v`. Bazı testler Windows/Tk, localhost ve gerçek overlay JavaScript harness'i için Node gerektirir. Bu aktarımda uygulama kaynak/test kodu değiştirilmedi; önceki **255/255** sonucu `.test-tmp/flicker-all-tests.txt` içinde korunur. Aktarımın belge/başlatıcı kontrolleri ayrıca yapılır. Özel profil/model indirmeden kod ve testler incelenebilir. Kullanıcı video/OCR/DB dosyaları depoda yoktur; gerekli saha kanıtı ayrıca kullanıcının kontrolünde paylaşılmalıdır.
