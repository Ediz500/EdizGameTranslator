# Test başlatıcıları

Normal kullanım başlatıcısı ana klasördeki `EDIZ_BASLAT.bat` olarak kalır ve
`dist/visual-stabilization-20261118` sürümünü açar. Bu klasördeki dosyalar onu
**değiştirmez**.

## Aşama 1 test sürümü — `ASAMA1_TEST_BASLAT.bat`

| | |
|---|---|
| EXE | `dist/stage1-single-translation-20261117/EdizGameTranslator/EdizGameTranslator.exe` |
| Profil | `local-data/stage1-single-translation-profile` (yalnız `settings.json`, görsel stabilizasyon profilinden kopya; eski veritabanı kopyalanmadı) |
| Kaynak | `projects/subtitle-flicker-fix`, `b053ceb` + commitlenmemiş Aşama 1 değişiklikleri (bkz. `CLAUDE_ASAMA1_SONUC.md`) |

Çalıştırma: önce açık Ediz Game Translator penceresini kapatın, sonra
`projects\subtitle-flicker-fix\tools\launchers\ASAMA1_TEST_BASLAT.bat`
dosyasına çift tıklayın. Başlatıcı ana klasörü kendi konumundan (`%~dp0..\..\..\..\`)
bulur; klasör taşınırsa çalışmaz.

Geri dönüş: test uygulamasını kapatın, ana klasördeki `EDIZ_BASLAT.bat` ile açın,
OBS'te `Ediz Türkçe Altyazı` kaynağını gerekirse bir kez yenileyin (eski sürümde
otomatik yenileme yoktur). Profil veya EXE kopyalamak gerekmez.

## Özel saha tekrar oynatma

`tools/benchmarks/replay_field.py`, bir profil veritabanının **kopyası** üzerindeki
kayıtlı ham OCR karelerini orijinal zaman damgalarıyla yeniden oynatır. Çıktıyı ve
kopyaları depoya eklemeyin; diyalog metni yalnız `--show-text` ile yerel konsolda
görünür.

```
python tools/benchmarks/replay_field.py --db <kopya.sqlite3> --session <oturum-öneki> --json <özel-çıktı.json>
```
