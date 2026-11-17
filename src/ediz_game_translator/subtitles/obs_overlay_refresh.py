"""Reload only Ediz's own OBS Browser Source(s) through obs-websocket.

OBS loads a Browser Source once. If the page was opened before this app's local
server existed, Chromium keeps its connection-error page and the overlay's own
reconnect logic never runs. Pressing the source's "refreshnocache" button
(obs-websocket v5 PressInputPropertiesButton) reloads it.

Strictly read-only otherwise: no scene/source/setting is created, changed or
removed; only browser inputs whose URL is exactly this app's overlay are touched.
"""
import time
from urllib.parse import urlparse

LOCAL_HOSTS = {'127.0.0.1', 'localhost'}
REFRESH_BUTTON = 'refreshnocache'


def overlay_url_matches(url, port):
    try:
        parsed = urlparse(str(url or '').strip())
        return (parsed.scheme == 'http' and parsed.hostname in LOCAL_HOSTS and parsed.port == int(port)
                and parsed.path.rstrip('/') in ('', '/overlay'))
    except (TypeError, ValueError):
        return False


def find_overlay_inputs(client, port):
    names = []
    for item in client.get_input_list(kind='browser_source').inputs:
        name = item.get('inputName') if isinstance(item, dict) else getattr(item, 'inputName', None)
        if not name:
            continue
        settings = client.get_input_settings(name).input_settings or {}
        if overlay_url_matches(settings.get('url'), port):
            names.append(name)
    return names


def refresh_overlay_inputs(client, port):
    names = find_overlay_inputs(client, port)
    for name in names:
        client.press_input_properties_button(name, REFRESH_BUTTON)
    return names


def ensure_overlay_connected(connect, browser_seen, port, *, attempts=3, wait=3.0, stop=None,
                             on_status=lambda message: None, clock=time.monotonic, sleep=time.sleep):
    """Refresh Ediz's Browser Source until the page reaches the local server.

    ``connect`` returns an object with ``.client`` (obsws ReqClient) and ``.close()``.
    ``browser_seen`` returns the monotonic time of the last overlay request (0 = never).
    Returns 'connected', 'not_found', 'obs_unavailable' or 'no_response'.
    """
    def connected(since):
        # >=: Windows monotonic() advances in 15.6 ms ticks, so a page that reconnects
        # within the same tick as the refresh carries the same timestamp.
        seen = browser_seen()
        return seen > 0 and seen >= since and clock() - seen < 2

    if connected(clock() - 2):
        on_status('OBS altyazı katmanı zaten bağlı.')
        return 'connected'
    for attempt in range(1, attempts + 1):
        if stop is not None and stop.is_set():
            return 'no_response'
        began = clock()
        try:
            source = connect()
            try:
                names = refresh_overlay_inputs(source.client, port)
            finally:
                source.close()
        except Exception as exc:
            on_status(f'OBS katmanı yenilenemedi ({type(exc).__name__}); deneme {attempt}/{attempts}.')
            names = None
        if names == []:
            on_status(f'OBS\'te http://127.0.0.1:{port}/overlay adresli Browser Source bulunamadı.')
            return 'not_found'
        if names:
            deadline = began + wait
            while clock() < deadline:
                if connected(began):
                    on_status('OBS altyazı katmanı otomatik yenilendi ve bağlandı: ' + ', '.join(names))
                    return 'connected'
                if stop is not None and stop.is_set():
                    return 'no_response'
                sleep(.1)
            on_status(f'OBS altyazı katmanı yanıt vermedi; deneme {attempt}/{attempts}.')
        elif stop is not None and stop.wait(wait):
            return 'no_response'
        elif stop is None:
            sleep(wait)
    on_status('OBS altyazı katmanı bağlanamadı. OBS\'te kaynağı elle yenileyin.')
    return 'obs_unavailable' if names is None else 'no_response'
