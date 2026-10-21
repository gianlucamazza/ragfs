import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ragfs_bench.adapters import BM25, RagfsCLI
from ragfs_bench.runner import prepare_models, read_fact, write_fact


class AdapterTests(unittest.TestCase):
    def test_bm25_uses_chunk_rank_not_unique_files(self):
        model = BM25([{'file_path': '/a/r1.md', 'chunk_index': 0, 'content': 'lighthouse'},
                      {'file_path': '/a/r1.md', 'chunk_index': 1, 'content': 'lighthouse'},
                      {'file_path': '/a/r2.md', 'chunk_index': 0, 'content': 'unrelated'}])
        self.assertEqual(model.retrieve('lighthouse', 2), ['r1', 'r1'])
        self.assertEqual(model.retrieve('nohit', 2), [])
        self.assertEqual(BM25([]).retrieve('anything', 5), [])

    def test_model_pins_verified_before_use(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = {}
            for name in ('config.json', 'tokenizer.json', 'model.safetensors'):
                (root / name).write_bytes(b'fixture')
                files[name] = {'path': name, 'sha256': hashlib.sha256(b'fixture').hexdigest()}
            manifest = root / 'model.json'
            manifest.write_text(json.dumps({'model': 'thenlper/gte-small', 'revision': 'a'*40, 'files': files}))
            prepare_models(manifest, root / 'data')
            self.assertEqual((root / 'data/models/models--thenlper--gte-small/refs/main').read_text(), 'a'*40)
            (root / 'model.safetensors').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                prepare_models(manifest, root / 'bad-data')

    def test_noop_cannot_be_measured(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {'RAGFS_TEST_EMBEDDER': 'noop'}):
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, 'must not use'):
                RagfsCLI(root/'binary', root/'snapshot', root, root/'data', root)

    def test_cli_modes_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {}, clear=True):
            root = Path(temp)
            cli = RagfsCLI(root/'binary', root/'snapshot', root, root/'data', root)
            self.assertIn('hybrid = false', cli.configs['vector'].read_text())
            self.assertIn('hybrid = true', cli.configs['ragfs'].read_text())
            self.assertEqual(cli.env['HF_HUB_OFFLINE'], '1')

    def test_cli_global_options_and_non_json_index_output(self):
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {}, clear=True):
            root = Path(temp)
            cli = RagfsCLI(root/'binary', root/'snapshot', root, root/'data', root)
            with patch('ragfs_bench.adapters.subprocess.run', return_value=CompletedProcess([], 0, 'Indexing complete\n', '')) as run:
                self.assertIsNone(cli.command('ragfs', 'index', str(root)))
                args = run.call_args.args[0]
                self.assertLess(args.index('--format'), args.index('index'))

    def test_answers_read_actual_frontmatter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = {'fact_id': 'f1', 'revision_id': 'r1', 'value': 'quoted: text', 'source': {'uri': 'fixture://r1'}}
            write_fact(root, record)
            self.assertEqual(read_fact(root, 'r1'), record)
            with self.assertRaisesRegex(ValueError, 'escapes'):
                read_fact(root, '../outside')
