import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import OpenAI
from scripts import setup


class ModelDiscoveryTests(unittest.TestCase):
    def fetch_response(self, status, payload):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(status, json=payload)

        def client(**kwargs):
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

        with patch('openai.OpenAI', side_effect=client):
            result = setup.fetch_upstream_models('https://relay.example', 'dummy-test-key')
        return result, requests

    def test_reads_models_with_normalized_endpoint_and_authorization(self):
        models, requests = self.fetch_response(200, {'data': [
            {'id': 'flux-test'}, {'id': 'gpt-image-test'}, {'id': ' flux-test '},
        ]})
        self.assertEqual(models, ['flux-test', 'gpt-image-test'])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, 'GET')
        self.assertEqual(str(requests[0].url), 'https://relay.example/v1/models')
        self.assertEqual(requests[0].headers['authorization'], 'Bearer dummy-test-key')

    def test_empty_list_is_supported(self):
        self.assertEqual(self.fetch_response(200, {'data': []})[0], [])

    def test_status_errors_do_not_show_server_body(self):
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status):
                with self.assertRaises(setup.ModelDiscoveryError) as error:
                    self.fetch_response(status, {'error': {'message': 'private-server-body'}})
                self.assertIn(str(status), str(error.exception))
                self.assertNotIn('private-server-body', str(error.exception))

    def test_invalid_urls_never_create_client(self):
        with patch('openai.OpenAI') as client:
            for url in ('file:///tmp/models', 'https://[', 'https://relay.example:bad', 'https://user:secret@relay.example'):
                with self.subTest(url=url), self.assertRaises(setup.ModelDiscoveryError):
                    setup.fetch_upstream_models(url, 'dummy-test-key')
            client.assert_not_called()

    def test_unexpected_sdk_value_error_is_sanitized(self):
        with patch('openai.OpenAI', side_effect=ValueError('private-sdk-detail')):
            with self.assertRaises(setup.ModelDiscoveryError) as error:
                setup.fetch_upstream_models('https://relay.example', 'dummy-test-key')
        self.assertNotIn('private-sdk-detail', str(error.exception))

    def test_non_list_payload_is_rejected(self):
        with patch('openai.OpenAI') as client:
            client.return_value.__enter__.return_value.models.list.return_value = SimpleNamespace(data={})
            with self.assertRaises(setup.ModelDiscoveryError):
                setup.fetch_upstream_models('https://relay.example', 'dummy-test-key')

    def test_image_name_filter_does_not_include_text_model(self):
        self.assertEqual(setup.likely_image_models(['chat-test', 'flux-test', 'gpt-image-test']), ['flux-test', 'gpt-image-test'])


class ModelDiscoveryGuiTests(unittest.TestCase):
    def run_gui(self, scenario, fetch, sources=None, advanced=True):
        import tkinter as tk
        from tkinter import ttk

        real_tk = tk.Tk
        failures = []

        def hidden_window():
            window = real_tk()
            window.withdraw()
            return window

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            if sources is not None:
                config.write_text(json.dumps({'sources': sources}), encoding='utf-8')

            def mainloop(window):
                widgets = list(descendants(window))
                entries = [widget for widget in widgets if isinstance(widget, ttk.Entry) and not isinstance(widget, ttk.Combobox)]
                combo = next(widget for widget in widgets if isinstance(widget, ttk.Combobox))
                buttons = {str(widget.cget('text')): widget for widget in widgets if isinstance(widget, ttk.Button)}
                checks = {str(widget.cget('text')): widget for widget in widgets if isinstance(widget, ttk.Checkbutton)}

                def pump_until(predicate):
                    deadline = time.monotonic() + 4
                    while not predicate():
                        if time.monotonic() > deadline:
                            raise AssertionError('GUI did not reach expected state')
                        window.update()
                        time.sleep(0.01)

                try:
                    scenario(window, entries, combo, buttons, checks, config, pump_until)
                except BaseException as error:
                    failures.append(error)
                finally:
                    for timer in window.tk.splitlist(window.tk.call('after', 'info')):
                        window.after_cancel(timer)
                    try:
                        window.destroy()
                    except tk.TclError:
                        pass

            with patch.object(tk, 'Tk', side_effect=hidden_window), patch.object(tk.Misc, 'mainloop', mainloop), patch.object(setup, 'ROOT_CONFIG', config), patch.object(setup, 'fetch_upstream_models', side_effect=fetch), patch('tkinter.messagebox.showinfo'), patch('tkinter.messagebox.showerror'):
                (setup.open_advanced_gui if advanced else setup.open_gui)()
        if failures:
            raise failures[0]

    def test_auto_fetch_filter_and_exact_selected_model_save(self):
        calls = []

        def fetch(url, key):
            calls.append((url, key))
            return ['chat-test', 'flux-test']

        def scenario(window, entries, combo, buttons, checks, config, pump):
            entries[1].insert(0, 'https://relay.example')
            entries[2].insert(0, 'dummy-test-key')
            pump(lambda: '上游 · flux-test' in combo.cget('values'))
            self.assertNotIn('上游 · chat-test', combo.cget('values'))
            self.assertEqual(len(calls), 1)
            combo.set('上游 · flux-test')
            buttons['保存配置'].invoke()
            self.assertEqual(json.loads(config.read_text(encoding='utf-8'))['sources'][0]['model'], 'flux-test')
            checks['显示全部模型'].invoke()
            self.assertIn('上游 · chat-test', combo.cget('values'))
            combo.set('上游 · chat-test')
            checks['显示全部模型'].invoke()
            buttons['保存配置'].invoke()
            self.assertEqual(json.loads(config.read_text(encoding='utf-8'))['sources'][0]['model'], 'chat-test')

        self.run_gui(scenario, fetch)

    def test_text_only_catalog_does_not_replace_configured_model(self):
        def scenario(window, entries, combo, buttons, checks, config, pump):
            entries[1].insert(0, 'https://relay.example')
            entries[2].insert(0, 'dummy-test-key')
            buttons['获取 / 刷新上游模型'].invoke()
            pump(lambda: not buttons['获取 / 刷新上游模型'].instate(['disabled']))
            buttons['保存配置'].invoke()
            self.assertEqual(json.loads(config.read_text(encoding='utf-8'))['sources'][0]['model'], setup.DEFAULT_MODEL)

        self.run_gui(scenario, lambda *_: ['chat-test'])

    def test_invalid_form_does_not_overwrite_saved_config(self):
        source = {'name': 'test', 'base_url': 'https://relay.example/v1', 'api_key': 'dummy-test-key', 'model': 'flux-test'}

        def scenario(window, entries, combo, buttons, checks, config, pump):
            before = config.read_bytes()
            entries[1].delete(0, 'end')
            buttons['保存配置'].invoke()
            self.assertEqual(config.read_bytes(), before)

        self.run_gui(scenario, lambda *_: [], sources=[source])

    def test_stale_response_is_ignored_after_changing_credentials(self):
        release = threading.Event()
        started = threading.Event()

        def fetch(url, key):
            if key == 'dummy-old':
                started.set()
                release.wait(3)
                return ['image-old']
            return ['image-new']

        def scenario(window, entries, combo, buttons, checks, config, pump):
            entries[1].insert(0, 'https://relay.example')
            entries[2].insert(0, 'dummy-old')
            buttons['获取 / 刷新上游模型'].invoke()
            pump(started.is_set)
            entries[2].delete(0, 'end')
            entries[2].insert(0, 'dummy-new')
            release.set()
            pump(lambda: '上游 · image-new' in combo.cget('values'))
            self.assertNotIn('上游 · image-old', combo.cget('values'))

        try:
            self.run_gui(scenario, fetch)
        finally:
            release.set()

    def test_simple_wizard_saves_one_source_without_advanced_controls(self):
        def scenario(window, entries, combo, buttons, checks, config, pump):
            entries[0].insert(0, 'https://relay.example')
            entries[1].insert(0, 'dummy-test-key')
            combo.set('Flare（推荐）')
            buttons['保存并完成'].invoke()
            saved = json.loads(config.read_text(encoding='utf-8'))
            self.assertEqual(saved['sources'][0]['base_url'], 'https://relay.example/v1')
            self.assertEqual(saved['sources'][0]['model'], 'gpt-image-2.5-flare')
        self.run_gui(scenario, lambda *_: [], advanced=False)


if __name__ == '__main__':
    unittest.main()
