"""Stage 1: exclusive overlay port, one app instance, automatic OBS Browser Source reload."""
from bootstrap import configure_paths
configure_paths()
import socket
import sys
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import urlopen

from ediz_game_translator.subtitles.obs_overlay_refresh import (
    ensure_overlay_connected, find_overlay_inputs, overlay_url_matches, refresh_overlay_inputs)
from ediz_game_translator.subtitles.overlay_server import SharedOverlayState, launch_server


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


class ReadOnlyFakeObs:
    """Only the read calls and the refresh button exist; any other OBS call fails the test."""
    def __init__(self, inputs, on_press=None):
        self.inputs = inputs; self.pressed = []; self.on_press = on_press

    def get_input_list(self, kind=None):
        assert kind == 'browser_source'
        return SimpleNamespace(inputs=[{'inputName': n, 'inputKind': 'browser_source'} for n in self.inputs])

    def get_input_settings(self, name):
        return SimpleNamespace(input_kind='browser_source', input_settings={'url': self.inputs[name]})

    def press_input_properties_button(self, name, prop):
        self.pressed.append((name, prop))
        if self.on_press:
            self.on_press()

    def __getattr__(self, name):
        raise AssertionError('Unexpected OBS call: ' + name)


class Connection:
    def __init__(self, client):
        self.client = client; self.closed = 0

    def close(self):
        self.closed += 1


@unittest.skipUnless(sys.platform == 'win32', 'Windows socket semantics')
class ExclusivePortTests(unittest.TestCase):
    def test_second_overlay_server_on_same_port_is_rejected(self):
        port = free_port(); first = launch_server(SharedOverlayState(), port)
        try:
            with self.assertRaises(OSError):
                launch_server(SharedOverlayState(), port)
            with urlopen(f'http://127.0.0.1:{port}/state', timeout=2) as response:
                self.assertEqual(response.status, 200)  # the first owner keeps serving
        finally:
            first.shutdown(); first.server_close()

    def test_older_reuse_style_listener_blocks_live_overlay(self):
        port = free_port()
        old = ThreadingHTTPServer(('127.0.0.1', port), BaseHTTPRequestHandler)  # previous EXE behaviour
        try:
            with self.assertRaises(OSError):
                launch_server(SharedOverlayState(), port)
        finally:
            old.server_close()

    def test_restart_after_real_connections_rebinds_immediately(self):
        port = free_port(); state = SharedOverlayState()
        server = launch_server(state, port)
        for _ in range(3):
            urlopen(f'http://127.0.0.1:{port}/state', timeout=2).read()
        server.shutdown(); server.server_close()
        again = launch_server(state, port)
        again.shutdown(); again.server_close()


@unittest.skipUnless(sys.platform == 'win32', 'Win32 mutex')
class SingleInstanceTests(unittest.TestCase):
    def test_second_instance_is_refused_and_released_on_close(self):
        from ediz_game_translator.storage.instance_lock import AppInstanceMutex
        name = 'Local\\EdizGameTranslator.Test.' + uuid.uuid4().hex
        first = AppInstanceMutex(name)
        with self.assertRaises(OSError):
            AppInstanceMutex(name)
        first.close()
        AppInstanceMutex(name).close()

    def test_mutex_is_shared_across_profiles(self):
        from ediz_game_translator.storage import instance_lock
        self.assertNotIn('config', instance_lock.APP_MUTEX_NAME.casefold())
        self.assertTrue(instance_lock.APP_MUTEX_NAME.startswith('Local\\'))


class ObsRefreshTests(unittest.TestCase):
    INPUTS = {'Ediz Türkçe Altyazı': 'http://127.0.0.1:8788/overlay',
              'Ediz localhost': 'http://localhost:8788/',
              'Kick Chat': 'https://chat.example.invalid/widget?bid=secret',
              'Other app': 'http://127.0.0.1:9999/overlay',
              'Look-alike': 'http://127.0.0.1.example.invalid:8788/overlay',
              'Broken': None}

    def test_only_this_apps_overlay_urls_match(self):
        self.assertTrue(overlay_url_matches('http://127.0.0.1:8788/overlay', 8788))
        self.assertTrue(overlay_url_matches('http://localhost:8788/overlay/', 8788))
        for url in ('https://127.0.0.1:8788/overlay', 'http://127.0.0.1:8789/overlay', 'http://192.168.1.2:8788/overlay',
                    'http://127.0.0.1:8788/state', 'file:///C:/overlay.html', '', None, 'http://[::1', 42):
            self.assertFalse(overlay_url_matches(url, 8788), url)

    def test_refresh_presses_only_matching_sources_and_nothing_else(self):
        client = ReadOnlyFakeObs(self.INPUTS)
        self.assertEqual(sorted(find_overlay_inputs(client, 8788)), sorted(['Ediz localhost', 'Ediz Türkçe Altyazı']))
        refresh_overlay_inputs(client, 8788)
        self.assertEqual(sorted(client.pressed),
                         sorted([('Ediz localhost', 'refreshnocache'), ('Ediz Türkçe Altyazı', 'refreshnocache')]))

    def test_reloaded_page_connecting_ends_retries(self):
        seen = [0.]; clock = [100.]
        client = ReadOnlyFakeObs({'Ediz': 'http://127.0.0.1:8788/overlay'}, on_press=lambda: seen.__setitem__(0, clock[0] + .3))
        def sleep(dt): clock[0] += dt
        messages = []; conn = Connection(client)
        result = ensure_overlay_connected(lambda: conn, lambda: seen[0], 8788, on_status=messages.append,
                                          clock=lambda: clock[0], sleep=sleep)
        self.assertEqual(result, 'connected'); self.assertEqual(len(client.pressed), 1); self.assertEqual(conn.closed, 1)
        self.assertIn('bağlandı', messages[-1])

    def test_already_connected_page_is_not_reloaded(self):
        clock = [100.]; client = ReadOnlyFakeObs({'Ediz': 'http://127.0.0.1:8788/overlay'})
        result = ensure_overlay_connected(lambda: Connection(client), lambda: 99.5, 8788, clock=lambda: clock[0])
        self.assertEqual(result, 'connected'); self.assertEqual(client.pressed, [])

    def test_bounded_retries_then_clear_status(self):
        clock = [100.]; client = ReadOnlyFakeObs({'Ediz': 'http://127.0.0.1:8788/overlay'}); messages = []
        def sleep(dt): clock[0] += dt
        result = ensure_overlay_connected(lambda: Connection(client), lambda: 0., 8788, attempts=3, wait=1.,
                                          on_status=messages.append, clock=lambda: clock[0], sleep=sleep)
        self.assertEqual(result, 'no_response'); self.assertEqual(len(client.pressed), 3)
        self.assertIn('elle yenileyin', messages[-1])

    def test_missing_source_and_unavailable_obs(self):
        messages = []
        self.assertEqual(ensure_overlay_connected(lambda: Connection(ReadOnlyFakeObs({'Kick': 'https://x.invalid'})),
                                                  lambda: 0., 8788, on_status=messages.append), 'not_found')
        stop = threading.Event(); calls = []
        def fail():
            calls.append(1)
            if len(calls) == 2: stop.set()
            raise ConnectionRefusedError()
        self.assertEqual(ensure_overlay_connected(fail, lambda: 0., 8788, wait=.01, stop=stop), 'no_response')
        self.assertEqual(len(calls), 2)
        self.assertEqual(ensure_overlay_connected(lambda: (_ for _ in ()).throw(OSError()), lambda: 0., 8788,
                                                  attempts=2, wait=.01), 'obs_unavailable')

    def test_app_restart_reconnects_without_manual_refresh(self):
        """Two app lifetimes on the same port: each start reloads the stale OBS page once."""
        port = free_port(); pressed = []
        for lifetime in range(2):
            state = SharedOverlayState(); server = launch_server(state, port)
            def reload_page():
                pressed.append(lifetime)
                threading.Thread(target=lambda: urlopen(f'http://127.0.0.1:{port}/overlay', timeout=2).read()).start()
            client = ReadOnlyFakeObs({'Ediz': f'http://127.0.0.1:{port}/overlay'}, on_press=reload_page)
            try:
                self.assertEqual(ensure_overlay_connected(lambda: Connection(client), lambda: state.browser_seen, port), 'connected')
            finally:
                server.shutdown(); server.server_close()
        self.assertEqual(pressed, [0, 1])


if __name__ == '__main__':
    unittest.main()
