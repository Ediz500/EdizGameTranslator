# Yayın öncesi sınırlı stabilizasyon

Temel: `codex/ui-live-sync-redesign`, `b0f6c92`. Yeni dal: `codex/prebroadcast-stabilization`. PR #3 ve çalışan sürüm değiştirilmedi. Başlangıçta çalışan süreç ve `dist/ui-live-sync-redesign/EdizGameTranslator/EdizGameTranslator.exe` yolu doğrulandı; EXE SHA-256: `cc484d651be6e0baa252655baf61bbd8b8a381e56c949f09545622cc3bcd519b`.

## Gerçek bulgular ve düzeltme

- Polling hataları yalnız yutuluyor, eski DOM metni/maske silinmiyordu. Yanıt vermeyen fetch için zaman aşımı yoktu.
- SSE sessiz takılınca `onerror` gelmeyebilir; istemcide güncellik kontrolü yoktu. Sunucunun 10 saniyelik SSE yorum keepalive’ı JavaScript `onmessage` olayına ulaşmıyordu.
- Kapanmış SSE nesnesine sıraya alınmış geç bir mesaj, polling ile alınmış yeni durumu eski durumla değiştirebiliyordu. Dört regresyon eski kaynakta bu sorunları yeniden üretti.

Yama yalnız `overlay_view.py` ve `overlay_server.py` üretim kodlarını değiştirir. Sunucu değişiklik olmasa da 500 ms’de bir tam güncel SSE snapshot’ı gönderir. İstemci 1.500 ms güncel snapshot alamazsa metin ve maskeyi temizleyip HTTP polling’e geçer. HTTP GET ve ACK için 800 ms AbortController sınırı vardır; polling 100 ms arayla tekrar denenir. Açık bağlantı hatası/bozuk yanıt da görünümü temizler. Eski bağlantı/istek ve eski animation-frame ACK’leri yerel nesil numarasıyla reddedilir. Yeniden bağlantıda son DOM kopyası oynatılmaz; yeni snapshot beklenir. Resize boşaltılmış görünümü geri getirmez.

Normal kaynak/oturum doğrulamaları `live_display.py` ve `live_sources.py` içinde aynen korunur. OCR, model, CUDA, çeviri işçisi, sözlük, maske geometrisi ve bağımlılıklar değiştirilmedi.

## İngilizcenin anlık görünmesi

Sentetik testlerde normal tek boş gözlem metni/maskeyi kaldırmıyor. En az iki boş gözlem ve 120 ms debounce dolunca ya da son kaynak gözleminden 600 ms geçince blok kaldırılıyor. Uzun bir OCR aralığında tek boş gözlem de bağımsız 600 ms sınırına denk gelebilir. Hızlı A→B’de B hazır değilse eski A ve maskesi kaldırılır. `layout.py` yalnız hazır çeviri bloklarından maske ürettiği için bu durumlarda İngilizce açığa çıkabilir. Gerçek oyundaki olayın hangi yoldan geldiği PS5 kaydıyla doğrulanmadı.

**Bu yama İngilizce flaşını tamamen çözmez.** Süreleri uzatmak eski Türkçeyi, koşulsuz boş maske tutmak yeni B’yi/oyun arayüzünü örtebilir. Yayın öncesi bu kuralları değiştirmedim. Sonraki küçük çalışma: ham görüntüde ilgili OCR kutusunun değişim/kararlılık kanıtını ayrı izlemek; kaynak değişince eski Türkçeyi hemen kaldırmak; yalnız doğrulanmış aynı bölgede, kısa ve kesin süre sınırı olan maske korumasını bağımsız OBS/native testleriyle değerlendirmek. Mevcut `ImageChangeGate` yalnız OCR planlamasını etkiliyor; böyle bir maske kanıtı sağlamıyor.

## Doğrulama

- Mevcut 201 test: **201/201 geçti**, 195,4 s (üretim kodu değişmeden; yalnız test portları izole edildi).
- Son toplu koşu: **218/218 geçti**, 159,0 s; skip yok. 12 JS bağlantı, 2 SSE ve 3 OCR/maske regresyonu eklendi.
- Ayrı Windows EXE, sentetik kamera + gerçek OCR, üç canlı blok, HTTP ACK=204, Tk hata=0 ve işçi kapanışı smoke testini geçti. Çeviri modeli bu testte yüklenmedi.
- Korunan kaynak ağacı (capture, translation, storage, core, layout, live_display, requirements) değişmedi. Çalışan EXE SHA-256 kontrolü aynı kaldı.

Test değişiklikleri: `test_daily_app.py` sabit 8788 yerine geçici port kullanır; çalışan uygulamaya temas etmez. `test_overlay_connection.py` / `overlay_connection_cases.js` gerçek gömülü JS’yi Node.js ile kontrollü DOM, ağ ve saat üzerinde çalıştırır; npm/AI paketi indirilmedi. `test_sse.py` gerçek localhost bağlantısında heartbeat ve güncel kaynakla yeniden bağlantıyı doğrular. `test_live_sync.py` tek/çok kare kaybını, bağımsız stale sınırını ve A→B sırasında eski metin/maskenin görünmemesini doğrular.

## Windows denemesi ve geri dönüş

1. Uygun zamanda mevcut çeviriyi durdurup eski uygulamayı kapatın. OBS ayarlarını değiştirmeyin. İki uygulama aynı 8788 portunu kullanır.
2. Ana proje klasöründe `STABILIZASYON_TEST_BASLAT.bat` çalıştırın. Ayrı EXE: `dist/prebroadcast-stabilization-20261118/EdizGameTranslator/EdizGameTranslator.exe`. Ayrı test profiline yalnız mevcut ayarlar birebir kopyalandı; eski SQLite/model/ortam yerinde kaldı.
3. OBS Browser Source’ta geçerli sayfanın önbelleğini yenileyin. URL aynı: `http://127.0.0.1:8788/overlay`. Bu adım eski JavaScript’in kullanılmasını önler. Kaynak/filtresiz sanal kamera yönünü değiştirmeyin.
4. Kısa konuşma, tek/çok kare OCR kaybı ve hızlı A→B deneyin. Browser Source bağlantısını kesip geri açın; eski replik kalmamalı, dönüşte yalnız güncel durum görünmeli. Güncel JS çalışırken sessiz bağlantı kaybı yaklaşık 1,5 saniyelik koruma süresinde temizlenmelidir.
5. Sorunda test sürümünü kapatıp `YENI_ARAYUZ_BASLAT.bat` ile önceki EXE’ye dönün ve OBS sayfasını tekrar yenileyin. Mevcut EXE’nin üzerine yazılmadı. Kaynak düzeltmesi tek commit ile geri alınabilir.

## Yayın için kalan riskler

Gerçek PS5/OBS Browser Source/TV testi yapılmadı. Node DOM testi gerçek CEF çizimi değildir; paket smoke testi de HDMI gecikmesi ölçmez. Browser/CEF veya işletim sistemi tamamen donarsa JavaScript timer’ı çalışamaz; 1,5 saniye fiziksel ekran için kesin garanti değildir. Maskenin İngilizceyi kısa süre açığa çıkarması yukarıdaki koşullarda devam edebilir. SSE kesildikten sonra bu sayfa polling ile devam eder; tekrar SSE’ye dönmek için sayfa yenilenir. Bağlantı yokken renderer ACK kaydı üretilemeyebilir.
