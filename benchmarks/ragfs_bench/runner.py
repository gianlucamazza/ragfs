"""Run the frozen eight-step scenario without publishing aggregate scores."""
from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .adapters import BM25, RagfsCLI
from .facts import answer, validate_facts
from .metrics import fact_match, lexical, recall
from .protocol import digest


def prepare_models(manifest: Path, data: Path) -> dict:
    pin = json.loads(manifest.read_text())
    if pin.get('model') != 'thenlper/gte-small' or not re.fullmatch(r'[0-9a-f]{40}', pin.get('revision', '')):
        raise ValueError('Model manifest requires gte-small and its full Hub revision')
    required = {'config.json', 'tokenizer.json', 'model.safetensors'}
    if set(pin.get('files', {})) != required:
        raise ValueError('Model manifest must pin config, tokenizer and safetensors')
    cache = data / 'models' / 'models--thenlper--gte-small'
    target = cache / 'snapshots' / pin['revision']
    target.mkdir(parents=True)
    for name, entry in pin['files'].items():
        source = (manifest.parent / entry['path']).resolve()
        if not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']) or digest(source) != entry['sha256']:
            raise ValueError(f'Model hash mismatch: {name}')
        shutil.copyfile(source, target / name)
        if digest(target / name) != entry['sha256']:
            raise ValueError(f'Model copy mismatch: {name}')
    (cache / 'refs').mkdir()
    (cache / 'refs' / 'main').write_text(pin['revision'])
    return pin


def write_fact(root: Path, record: dict):
    # JSON values are valid YAML values; front matter remains explicit and machine readable.
    lines = [f'{key}: {json.dumps(value)}' for key, value in record.items()]
    path = root / (record['revision_id'] + '.md')
    path.write_text('---\n' + '\n'.join(lines) + '\n---\n\n' +
                    f"{record['fact_id']}: {record['value']}\n")


def read_fact(root: Path, revision_id: str) -> dict:
    path = root / (revision_id + '.md')
    if path.resolve().parent != root.resolve():
        raise ValueError('Fact revision escapes corpus')
    body = path.read_text()
    if not body.startswith('---\n'):
        raise ValueError('Retrieved fact has no front matter')
    front, _ = body[4:].split('\n---\n', 1)
    record = {key: json.loads(value) for key, value in
              (line.split(': ', 1) for line in front.splitlines())}
    if record['revision_id'] != revision_id:
        raise ValueError('Retrieved fact revision differs from file name')
    return record


def run(protocol_path, protocol, pins, facts, queries, *, binary, snapshot, model_manifest, output):
    if protocol["query"].get("hybrid") is not True:
        raise ValueError("This frozen protocol requires hybrid=true for ragfs; vector is always dense-only")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    data, root = output / 'data', output / 'corpus'
    root.mkdir()
    model_pin = prepare_models(model_manifest.resolve(), data)
    cli = RagfsCLI(binary, snapshot, root, data, output)
    lookup = validate_facts(facts)
    cases, revisions = [], []
    try:
        for phase in (1, 2):
            active = facts[:1] if phase == 1 else facts
            for record in active:
                write_fact(root, record)
            revision = cli.index()
            if revisions and revision <= revisions[-1]:
                raise ValueError('Content write did not advance index revision')
            revisions.append(revision)
            chunks = cli.chunks()
            (output / f'phase-{phase}-chunks.json').write_text(json.dumps(chunks, indent=2))
            bm25 = BM25(chunks)
            for query in [q for q in queries if q['phase'] == phase]:
                gold = answer(active, query, lookup)
                for system in protocol['systems']:
                    started = time.perf_counter()
                    if system == 'bm25':
                        ids, receipt = bm25.retrieve(query['text'], protocol['query']['k']), None
                    else:
                        ids, receipt = cli.retrieve(system, query, protocol['query']['k'])
                    retrieved = [read_fact(root, rid) for rid in dict.fromkeys(ids) if rid in lookup]
                    # Only explicit predecessor links may perform direct corpus lookup.
                    predecessors = {record['supersedes']: read_fact(root, record['supersedes'])
                                    for record in retrieved if record['supersedes'] is not None}
                    prediction = answer(retrieved, query, predecessors)
                    latency = time.perf_counter() - started
                    retrieval = recall(ids, query['gold_ids'], protocol['query']['k'])
                    case = {'id': query['id'], 'system': system, 'ability': query['ability'],
                            'prediction': prediction, 'retrieved_ids': ids,
                            'latency_s': latency, 'cost_usd': 0,
                            'exact_match_strict': fact_match(prediction, gold),
                            'exact_match_lenient': fact_match(prediction, gold, lenient=True),
                            'lexical_fields': {field: {
                                mode: dict(zip(('em', 'f1'), lexical(prediction[field], gold[field], lenient=mode == 'lenient')))
                                for mode in ('strict', 'lenient')
                            } for field in ('current', 'replaced')},
                            'source_exact': prediction['source'] == gold['source'],
                            'recall': retrieval, 'index_revision': revision,
                            'fingerprint': {k: receipt.get(k) for k in ('embedding_model','embedding_dim','min_alnum_chars')} if receipt else None}
                    raw = output / 'raw' / system / (query['id'] + '.json')
                    raw.parent.mkdir(parents=True, exist_ok=True)
                    raw.write_text(json.dumps(case, indent=2) + '\n')
                    cases.append(case)
        repo = Path(__file__).resolve().parents[2]
        git_sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = bool(subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip())
        result = {'schema_version': 1, 'protocol_id': protocol['protocol_id'],
                  'protocol_sha256': digest(protocol_path), 'git_sha': git_sha, 'git_dirty': dirty,
                  'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                  'environment': {'os': platform.platform(), 'arch': platform.machine(),
                                  'cpu_model': platform.processor(), 'python': platform.python_version(),
                                  'ragfs_binary_sha256': digest(binary), 'snapshot_binary_sha256': digest(snapshot),
                                  'cargo_lock_sha256': digest(repo / 'Cargo.lock'),
                                  'latency_scope': 'CLI includes startup, status checks and receipt I/O; BM25 is in-process, not a fair speed comparison'},
                  'pins': pins, 'model_pin': model_pin, 'systems': protocol['systems'], 'judge': None,
                  'metrics': [], 'cases': cases, 'write_revisions': revisions,
                  'publication_status': 'raw local evidence; no aggregate score'}
        (output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
    except Exception as error:
        (output / 'failure.json').write_text(json.dumps({'error': str(error), 'completed_cases': cases}, indent=2))
        raise
