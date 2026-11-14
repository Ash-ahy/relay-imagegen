import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import relay_imagegen
from scripts.image_client import ImageDownloadError
from test_image_client import png_bytes


class DownloadRecoveryTests(unittest.TestCase):
    def test_failed_download_saves_recovery_without_generation_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.json'
            config.write_text(json.dumps({'api_key': 'dummy-key', 'base_url': 'https://relay.test/v1'}))
            out = root / 'kitten.png'
            error = ImageDownloadError('Image download certificate verification failed', 'https://images.test/a?signature=private')
            with patch('sys.argv', ['relay_imagegen', 'generate', '--config', str(config), '--prompt', 'kitten', '--out', str(out)]), patch.object(relay_imagegen, 'request_with_failover', side_effect=error) as request:
                with self.assertRaises(SystemExit):
                    relay_imagegen.main()
            request.assert_called_once()
            record = json.loads(out.with_suffix('.download.json').read_text(encoding='utf-8'))
            self.assertEqual(record['url'], error.url)
            self.assertNotIn('dummy-key', json.dumps(record))
            self.assertFalse(out.exists())

    def test_recovery_never_loads_credentials_or_calls_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / 'kitten.png'
            record = root / 'kitten.download.json'
            record.write_text(json.dumps({'url': 'https://images.test/a', 'output': str(out), 'size': '2x3', 'metadata': {'model': 'test-model'}}))
            with patch('sys.argv', ['relay_imagegen', '--retry-download', str(record)]), patch.object(relay_imagegen, 'load_config') as config, patch.object(relay_imagegen, 'ImageClient') as client, patch.object(relay_imagegen, 'extract_image_bytes', return_value=png_bytes()):
                self.assertEqual(relay_imagegen.main(), 0)
            config.assert_not_called()
            client.assert_not_called()
            self.assertTrue(out.exists())
            self.assertFalse(record.exists())
            self.assertTrue(json.loads(out.with_suffix('.meta.json').read_text())['download_recovered'])

    def test_recovery_failure_keeps_record_and_does_not_generate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / 'kitten.png'
            record = root / 'kitten.download.json'
            record.write_text(json.dumps({'url': 'https://images.test/a', 'output': str(out), 'size': '2x3', 'metadata': {}}))
            with patch('sys.argv', ['relay_imagegen', '--retry-download', str(record)]), patch.object(relay_imagegen, 'ImageClient') as client, patch.object(relay_imagegen, 'extract_image_bytes', side_effect=ImageDownloadError('certificate failed', 'https://images.test/a')):
                with self.assertRaises(SystemExit):
                    relay_imagegen.main()
            client.assert_not_called()
            self.assertTrue(record.exists())
            self.assertFalse(out.exists())
