"""Retrieval adapters over identical product-produced chunk boundaries."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
from collections import Counter
from pathlib import Path


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


class BM25:
    """Reference BM25 v1: k1=1.5, b=.75, positive Robertson IDF, Unicode words.

    Corpus inputs are the actual chunk texts exported by benchmark_snapshot.
    No vectors, generation model or fact-id prefilter is used.
    """
    def __init__(self, chunks: list[dict]):
        self.chunks = sorted(chunks, key=lambda c: (c['file_path'], c['chunk_index']))
        self.counts = [Counter(tokens(chunk['content'])) for chunk in self.chunks]
        self.lengths = [sum(count.values()) for count in self.counts]
        self.average = sum(self.lengths) / len(self.lengths) if self.lengths else 1
        self.df = Counter(term for count in self.counts for term in count)

    def retrieve(self, query: str, k: int) -> list[str]:
        scores = []
        for i, count in enumerate(self.counts):
            score = 0.
            for term in tokens(query):
                frequency = count[term]
                if frequency:
                    idf = math.log(1 + (len(self.counts) - self.df[term] + .5) / (self.df[term] + .5))
                    score += idf * frequency * 2.5 / (frequency + 1.5 * (.25 + .75 * self.lengths[i] / self.average))
            if score > 0:
                scores.append((score, i))
        ranked = sorted(scores, key=lambda item: (-item[0], item[1]))[:k]
        # Keep chunk ranks (including duplicate file ids) for the recall denominator.
        return [Path(self.chunks[i]['file_path']).stem for _, i in ranked]


class RagfsCLI:
    def __init__(self, binary: Path, snapshot: Path, root: Path, data: Path, output: Path):
        self.binary, self.snapshot = binary.resolve(), snapshot.resolve()
        self.root, self.data, self.output = root, data, output
        self.env = dict(os.environ, RAGFS_DATA_DIR=str(data), HF_HUB_OFFLINE='1')
        if self.env.get('RAGFS_TEST_EMBEDDER'):
            raise ValueError('Measured runs must not use RAGFS_TEST_EMBEDDER')
        self.configs = {}
        for system in ('vector', 'ragfs'):
            config = output / f'{system}.toml'
            config.write_text('[embedding]\nmodel = "thenlper/gte-small"\nuse_gpu = false\n'
                              '[query]\nhybrid = ' + str(system == 'ragfs').lower() + '\n')
            self.configs[system] = config

    def command(self, system: str, *args: str) -> dict | None:
        result = subprocess.run([str(self.binary), '--config', str(self.configs[system]), '--format', 'json', *args],
                                env=self.env, text=True, capture_output=True, timeout=600, check=True)
        return json.loads(result.stdout) if args[0] != 'index' and result.stdout.strip() else None

    def index(self) -> int:
        self.command('ragfs', 'index', str(self.root))
        return self.revision()

    def revision(self) -> int:
        return self.command('ragfs', 'status', str(self.root))['index_revision']

    def chunks(self) -> list[dict]:
        stores = list((self.data / 'indices').glob('*/index.lance'))
        if len(stores) != 1:
            raise ValueError('Expected exactly one isolated benchmark store')
        result = subprocess.run([str(self.snapshot), str(stores[0])], env=self.env, text=True,
                                capture_output=True, timeout=120, check=True)
        return json.loads(result.stdout)

    def retrieve(self, system: str, query: dict, k: int) -> tuple[list[str], dict]:
        receipt = self.output / 'raw' / system / (query['id'] + '.receipt.json')
        receipt.parent.mkdir(parents=True, exist_ok=True)
        before = self.revision()
        result = self.command(system, 'query', str(self.root), query['text'],
                              '--limit', str(k), '--save-receipt', str(receipt))
        if result['index_revision'] != before or self.revision() != before:
            raise ValueError('Read-only query changed index revision')
        if result['embedding_model'] != 'thenlper/gte-small' or result['embedding_dim'] != 384:
            raise ValueError('Unexpected embedding fingerprint')
        saved = json.loads(receipt.read_text())
        if saved['results'] != result['results'] or saved['index_revision'] != before:
            raise ValueError('Receipt differs from query output')
        return [Path(item['file']).stem for item in result['results']], result
