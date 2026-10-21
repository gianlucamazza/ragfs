import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from ragfs_bench.__main__ import validate
from ragfs_bench.facts import abstention, answer, validate_facts
from ragfs_bench.metrics import fact_match, lexical, recall
from ragfs_bench.protocol import load_protocol, read_jsonl

ROOT = Path(__file__).resolve().parents[1]


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'fixtures', self.root / 'fixtures')
        for name in ('protocol.toml', 'pins.toml'):
            shutil.copy(ROOT / name, self.root / name)

    def test_checked_in_protocol_and_fixture(self):
        protocol, pins, facts, queries = validate(self.root / 'protocol.toml')
        self.assertEqual(len(facts), 2)
        self.assertEqual(len(queries), 4)
        self.assertEqual(len(pins), 3)
        self.assertEqual(protocol['query']['k'], 5)

    def test_corrupt_artifact_fails(self):
        with (self.root / 'fixtures/facts.jsonl').open('a') as out:
            out.write('\n')
        with self.assertRaisesRegex(ValueError, 'Pin mismatch'):
            load_protocol(self.root / 'protocol.toml')

    def test_floating_pin_fails(self):
        path = self.root / 'pins.toml'
        text = path.read_text()
        import re
        path.write_text(re.sub(r'revision = "[^"]+"', 'revision = "main"', text))
        with self.assertRaisesRegex(ValueError, 'immutable'):
            load_protocol(self.root / 'protocol.toml')

    def test_invalid_protocol_fails(self):
        path = self.root / 'protocol.toml'
        path.write_text(path.read_text().replace('k = 5', 'k = 0'))
        with self.assertRaisesRegex(ValueError, 'positive'):
            validate(path)


class FactTests(unittest.TestCase):
    def setUp(self):
        self.facts = read_jsonl(ROOT / 'fixtures/facts.jsonl')
        self.queries = read_jsonl(ROOT / 'fixtures/queries.jsonl')

    def test_current_history_unknown_and_half_open_boundary(self):
        lookup = validate_facts(self.facts)
        initial, updated, historical, unknown = [answer(self.facts, q, lookup) for q in self.queries]
        self.assertEqual(initial['current'], 'Globex')
        self.assertEqual(updated['current'], 'Acme')
        self.assertEqual(updated['replaced'], 'Globex')
        self.assertEqual(updated['source']['uri'], 'synthetic:s2')
        self.assertEqual(initial, historical)
        self.assertEqual(unknown, abstention())
        query = dict(self.queries[0], at='2025-02-01T00:00:00Z')
        self.assertEqual(answer(self.facts, query, lookup)['current'], 'Acme')

    def test_answer_cannot_select_unretrieved_current(self):
        lookup = validate_facts(self.facts)
        self.assertEqual(answer(self.facts[:1], self.queries[1], lookup), abstention())

    def test_overlap_rejected(self):
        self.facts[0]['valid_to'] = None
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            validate_facts(self.facts)

    def test_fork_and_cycle_rejected(self):
        extra = copy.deepcopy(self.facts[1])
        extra['revision_id'] = 'fork'
        with self.assertRaisesRegex(ValueError, 'Nonlinear'):
            validate_facts(self.facts + [extra])
        self.facts[0]['supersedes'] = self.facts[1]['revision_id']
        with self.assertRaisesRegex(ValueError, 'earlier'):
            validate_facts(self.facts)

    def test_invalid_sentinel_and_source_rejected(self):
        self.facts[1]['value'] = None
        with self.assertRaisesRegex(ValueError, 'sentinel'):
            validate_facts(self.facts)


class MetricTests(unittest.TestCase):
    def test_normalization_and_articles(self):
        self.assertEqual(lexical('Ａcme', 'Acme')[0], 1)
        self.assertEqual(lexical('acme', 'Acme')[0], 0)
        self.assertEqual(lexical(' THE  Acme ', 'Acme', lenient=True, free_text=True)[0], 1)
        self.assertEqual(lexical('The Acme', 'Acme', lenient=True)[0], 0)
        self.assertEqual(lexical(None, '')[0], 0)
        self.assertEqual(lexical('a a b', 'a b b')[1], 2/3)

    def test_retrieval_denominators(self):
        self.assertEqual(recall(['a', 'a', 'b'], ['a', 'b'], 2), {'any': 1., 'all': 0., 'frac': .5})
        self.assertEqual(recall(['a'], [], 5), {'any': None, 'all': None, 'frac': None})

    def test_source_identity_is_not_normalized(self):
        gold = {'current': 'The Acme', 'replaced': None, 'source': {'uri': 'S1', 'kind': 'document'}}
        pred = copy.deepcopy(gold)
        pred['source']['uri'] = 's1'
        self.assertFalse(fact_match(pred, gold, lenient=True))


if __name__ == '__main__':
    unittest.main()
