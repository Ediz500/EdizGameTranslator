# Proje dosya envanteri — 17 Kasım 2026

Ana proje klasöründe **88039 dosya, 7.217 GiB** metadata envanteri çıkarıldı. Okuma hatası veya atlanan reparse/junction yok. Bu, envanter anında görülen dosya boyutlarının toplamıdır; disk tahsis boyutu değildir. Görevde sonradan eklenen küçük belge/başlatıcılar sayıyı değiştirebilir. Ana klasör dışındaki OBS videoları veya sistem CUDA kurulumu taşınmadı/taranmadı.

Tam yollar/metadata ve BAT içerikleri yalnız özel `.test-tmp/github-transfer-20261117/inventory-private.jsonl`, `inventory-summary-private.json` ve `DOSYA_ENVANTERI_YEREL.md` dosyalarındadır; bu dosyalar GitHub’a gönderilmez.

| Sınıf | Dosya | GiB | İşlem |
|---|---:|---:|---|
| Önceki kaynaklar / worktree | 1327 | 0.008 | Korundu; taşınmadı/silinmedi |
| EXE paketleri | 24880 | 2.555 | Korundu; taşınmadı/silinmedi |
| Derleme ara çıktıları | 160 | 0.420 | Korundu; taşınmadı/silinmedi |
| Kişisel profiller | 26 | 0.020 | Korundu; taşınmadı/silinmedi |
| Sanal ortamlar | 59136 | 2.728 | Korundu; taşınmadı/silinmedi |
| Yerel modeller | 25 | 0.665 | Korundu; taşınmadı/silinmedi |
| İndirme önbelleği | 221 | 0.772 | Korundu; taşınmadı/silinmedi |

## Kaynaklar ve Git ağaçları

- Güncel geliştirme: `projects/subtitle-flicker-fix`, `codex/subtitle-flicker-fix`.
- Üç önceki kaynak: `projects/ui-live-sync-redesign`, `projects/prebroadcast-stabilization`, `projects/visual-stabilization`.
- Bu dört worktree aynı ortak Git deposunu paylaşır. İşlem başında hepsi temizdi.
- Ana klasörde ayrı `master` deposu: 8 değiştirilmiş takipli dosya ve 12 untracked durum girdisi vardı. Kök Python dosyaları eski çalışma kopyasıdır; günlük kaynak diye üzerine yazılmadı.
- İki deponun tüm ref’leri Git bundle olarak yedeklendi ve `git bundle verify` ile doğrulandı; beş çalışma ağacının patch’i ile kök eski kaynakların ZIP’i yerelde korundu.

## EXE paketleri ve geri dönüş

| `dist/` altındaki sürüm | Sınıflandırma |
|---|---|
| `EdizGameTranslator` | Önceki sürüm / geri dönüş adayı; silinmez |
| `local-development` | Önceki sürüm / geri dönüş adayı; silinmez |
| `local-development-final` | Önceki sürüm / geri dönüş adayı; silinmez |
| `local-only-cleanup` | Önceki sürüm / geri dönüş adayı; silinmez |
| `optimization` | Önceki sürüm / geri dönüş adayı; silinmez |
| `prebroadcast-stabilization-20261118` | Önceki sürüm / geri dönüş adayı; silinmez |
| `subtitle-flicker-fix-20261117` | Deneysel: 255 test, gerçek PS5’te flicker sürüyor |
| `ui-live-sync-redesign` | Önceki sürüm / geri dönüş adayı; silinmez |
| `visual-stabilization-20261118` | Normal tercih: gerçek PS5’te denenmiş görsel sürüm; bilinen hatalar sürüyor |

Toplam 9 dağıtım paketi ve `build/` altında 10 EXE kaydı var. SHA-256 karşılaştırmasında 9 dağıtım EXE’si birer build EXE’siyle eşleşti. Bu, `_internal` bağımlılık klasörlerinin birebir aynı veya gereksiz olduğunu kanıtlamaz. Farklı sürümlerin EXE hash’leri farklıdır; klasör adına bakarak kopya sayılmaz.

## Model, CUDA ve Python ortamları

Beş sanal ortam:
- `.test-tmp/local-nmt-env`
- `.test-tmp/local-only-env`
- `.test-tmp/ui-redesign-env`
- `.venv`
- `.venv-win`

Aktif model/Python başvuruları `.test-tmp/local-models/opus-en-tr/ct2-int8` ve `.test-tmp/local-nmt-env/Scripts/python.exe`. Dört gerçek profil aynı CUDA / `int8_float16` yolunu kullanır. Bu yollar mutlak olarak kaydedildiği için klasör taşımak çalışan çeviriyi bozabilir. Model ve CUDA/Python ortamı silinmez veya taşınmaz.

## Özel kayıtlar ve test çıktıları

`local-data` profilleri, ana klasördeki özel SQLite dosyaları, `benchmark-private`, `.test-tmp/flicker-private`, OCR/benchmark JSON kayıtları ve günlükler özel kabul edilir. OBS parolası/anahtarlar yayımlanmaz. Envanter ad/boyut/zaman metadata’sını kaydeder; veritabanı ve özel OCR/video günlük içerikleri okunmadı. Profillerde yalnız çalışma ortamı/model yolları salt okunur doğrulandı. Kişisel veritabanları açılıp yazılmadı.

`build/`, pip indirme önbelleği ve eski raporlar ancak sonraki, onaylı dosya bazlı incelemede temizleme adayıdır. `.test-tmp` geçici adı taşısa da çalışan ortamları içerir; topluca silinemez.

## Başlatıcılar ve önerilen sadeleşme

`EDIZ_BASLAT.bat` tek normal giriş olarak eklenir; hedefi görsel stabilizasyon EXE’si ve mevcut görsel profildir. Kök `BASLAT.bat`, `YENI_ARAYUZ_BASLAT.bat`, `STABILIZASYON_TEST_BASLAT.bat`, `GORSEL_STABILIZASYON_BASLAT.bat`, `FLICKER_TEST_BASLAT.bat`, `KURULUM.bat` ve `PAKETLE.bat` korunur. Kurulum/paketleme BAT’ları günlük başlatıcı değildir.

Öneri: mevcut `dist`, `projects`, ortam/model ve `local-data` yollarını koruyup önce belge/başlatıcı üzerinden sade bir giriş sunmak. Sonraki onaylı aşamada kök eski raporlar `arsiv/raporlar` altında, önceki sürüm erişim açıklamaları `arsiv/geri-donusler` altında düzenlenebilir. BAT taşınacaksa `%~dp0` bağımlılıkları yeniden doğrulanır; worktree için Explorer taşıması/force remove kullanılmaz. **Bu görevde taşıma veya silme uygulanmadı.**

Güncel durum, sürüm zinciri ve bağımsız inceleme kapsamı: [PROJE_DURUMU.md](../../PROJE_DURUMU.md).
