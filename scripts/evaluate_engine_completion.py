"""Price-only baseline, full-engine repetition, search timing, and extreme budgets.

Use MOCK_MODE=1. Real frozen catalog/review inputs; no external IO or service writes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import signal
import statistics
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import evaluate_engine_minimum_ablation as experiment

EXTREME_BUDGETS = (-1, 0, 1, 50000, 100000, 500000, 10000000, 100000000)


class MeasurementTimeout(TimeoutError):
    pass


@contextmanager
def deadline(seconds):
    previous = signal.getsignal(signal.SIGALRM)
    def expired(*_):
        raise MeasurementTimeout(f'measurement exceeded {seconds:g}s')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def cheapest_search(pools, slots, budget, spec, rules, wide_pools=None, *, node_cap=2000000):
    """Independent invocation of a price-only search on ALL hardfilter survivors.

    Shares engine validity predicates, but never uses score or the top-N shortlist.
    Only uncapped search is reported as a proven minimum. Budget validity remains
    checked by the ordinary build/verifier; an over-budget minimum is diagnostic.
    """
    from src.engine import stage4_optimize as optimizer
    if wide_pools is None:
        raise ValueError('full candidate pools are required for the price baseline')
    order = [s for s in ('메인보드', '케이스', 'CPU', 'RAM', 'GPU', '쿨러', '파워', '저장장치') if s in slots]
    order.extend(s for s in slots if s not in order)
    counts = {'considered': math.prod(len(wide_pools[s]) for s in slots), 'visited': 0,
              'valid': 0, 'pruned_budget': 0, 'pruned_compat': 0, 'pruned_required_missing': 0,
              'pruned_requirement_unmet': 0, 'pruned_score': 0, 'feasible': 0, 'compatible': 0}
    chosen = optimizer._cheapest_compatible(wide_pools, order, spec, rules, counts, node_cap)
    counts['visited'] = counts['cheapest_visited']
    counts['global_minimum_proven'] = int(not counts.get('capped'))
    counts['feasible'] = int(bool(chosen) and sum(c.price for c in chosen.values()) <= budget)
    counts['compatible'] = int(bool(chosen))
    return chosen, counts, bool(chosen)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def extreme_requests():
    return [{'id': f'{p}|none|noise={int(noise)}|{b}',
             'values': {'category': 'computer', 'mode': 'build', 'purpose': p,
                        'noise_sensitive': noise, 'budget_max': b,
                        **({'resolution': 'FHD_144'} if p == 'game' else {})}}
            for p in experiment.MINIMUM for b in EXTREME_BUDGETS for noise in (False, True)]


def distribution(values):
    import numpy as np
    return {'n': len(values), 'p50': statistics.median(values),
            'p95': float(np.percentile(values, 95)), 'max': max(values),
            'mean': statistics.mean(values), 'population_std': statistics.pstdev(values)} if values else None


def main():
    if os.environ.get('MOCK_MODE') != '1':
        raise SystemExit('MOCK_MODE=1 is required')
    from scripts import engine_policy_compare as compare
    from src.categories import load_category
    from src.dto import Candidate
    from src.engine import feasibility, research_loop, stage2_requirement, stage4_optimize as optimizer
    from src.engine.slots import slots_from_conditions
    from src.services import review_ranking
    from src.services.cold_start_data import CONFIGS, assert_configuration
    import yaml
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--pilot', action='store_true')
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit('output directory exists; use a new directory')
    snapshot_path = ROOT/'outputs/cold_start_policy/20261020_v1/snapshot/catalog.json'
    snapshot = experiment.read(snapshot_path)
    assert_configuration(snapshot)
    catalog = {s: [Candidate.model_validate(c) for c in cs] for s, cs in snapshot['catalog'].items()}
    raw = {s: {c['product_key']: c for c in cs} for s, cs in snapshot['catalog'].items()}
    benchmarks = yaml.safe_load((ROOT/'config/performance_benchmarks.yaml').read_text())['products']
    normal, extremes, repeats = experiment.requests(), extreme_requests(), 5
    if args.pilot:
        normal, repeats = normal[::8], 2
        extremes = [r for r in extremes if r['values']['budget_max'] in (0, 100000000) and not r['values']['noise_sensitive']]
    tracked = [snapshot_path, Path(__file__), ROOT/'scripts/evaluate_engine_minimum_ablation.py',
               ROOT/'scripts/engine_policy_compare.py', *(ROOT/n for n in CONFIGS), *sorted((ROOT/'src').rglob('*.py'))]
    before = {str(p.relative_to(ROOT)): experiment.sha(p) for p in tracked}
    args.out.mkdir(parents=True)
    for path in tracked:
        destination = args.out/'executor_snapshot'/path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    experiment.write(args.out/'plan.json', {'normal_requests': normal, 'extreme_requests': extremes,
        'repetitions': repeats, 'case_timeout_seconds': 20, 'price_node_cap': 2000000,
        'timing': 'sum perf_counter_ns duration of _search_pc_build, including widened and fallback search; excludes rank and verify',
        'price_baseline': 'full Pass pools, exact minimum total price when uncapped, shared validity predicates, no score/top-N objective',
        'repeat_signature': 'final SKU/qty, total/score, all slot ranks/scores/breakdowns, eligibility and verification; excludes timing/UUID',
        'input_sha256': before, 'snapshot_exported_at': snapshot['exported_at'],
        'scope': 'engine stages 2/3a/3b/4/3c and research, frozen catalog/review, no live enrichment',
        'api_calls': 0, 'database_calls': 0, 'runtime_policy_changes': 0})
    original_search, original_stage4 = optimizer._search_pc_build, optimizer.run
    def no_io(*_a, **_kw):
        raise AssertionError('external IO is blocked')
    def frozen_review(_conn, version, ids):
        assert version == snapshot['review']['analysis_version']
        assert all(str(i) in snapshot['review']['products'] for i in ids)
        return copy.deepcopy(snapshot['review'])
    records = []
    def execute(request, suite, repeat_index=0):
        search_trace, stage4_trace = [], []
        rec = {'id': request['id'], 'values': copy.deepcopy(request['values']),
               'suite': suite, 'repeat_index': repeat_index}
        def search(*a, **kw):
            start = time.perf_counter_ns()
            trace = {}
            try:
                result = (cheapest_search if suite == 'cheapest' else original_search)(*a, **kw)
                trace['counts'] = result[1]
                if result[0]:
                    trace['selected_price'] = sum(c.price for c in result[0].values())
                return result
            finally:
                trace['elapsed_ms'] = (time.perf_counter_ns()-start)/1e6
                search_trace.append(trace)
        def stage4(*a, **kw):
            start = time.perf_counter_ns()
            try:
                return original_stage4(*a, **kw)
            finally:
                stage4_trace.append((time.perf_counter_ns()-start)/1e6)
        started = time.perf_counter_ns()
        try:
            with deadline(20), patch.object(optimizer, '_search_pc_build', search), patch.object(optimizer, 'run', stage4):
                cat = load_category('computer')
                slots = slots_from_conditions('computer', cat, rec['values'])
                spec = stage2_requirement.run(slots, cat, lambda _: None)
                spec.list_id = request['id']
                by_slot = {s: [c.model_copy(deep=True) for c in cs] for s, cs in catalog.items()}
                available = feasibility.assess(spec, by_slot)
                spec.budget.update(feasibility=available['level'], feasibility_detail=available)
                flow = compare.engine_flow(spec, slots, by_slot, enricher=experiment.FrozenEnricher(), conn=object(), catalog_source='db')
            rec['engine_ms'] = (time.perf_counter_ns()-started)/1e6
            rec.update(compare.flow_fields(flow, compare._quiet_aspects()))
            chosen = research_loop.resolve_chosen(flow.rank, flow.build)
            selected = {s: c.model_dump(mode='json') for s, c in chosen.items()}
            rec['build_identity'] = {s: [c.product_key, c.purchase_qty] for s, c in sorted(chosen.items())}
            rec['minimum'] = experiment.minimum_check(rec['values'], selected, raw)
            rec['mean_axis_scores'] = {a: statistics.mean(c.breakdown[a] for c in chosen.values()) for a in experiment.AXES}
            weights = flow.rank.weights_used
            rec['baseline_weighted_fit_score'] = math.fsum(weights[a]*rec['mean_axis_scores'][a] for a in experiment.AXES)
            rec['benchmarks'] = {}
            for s in ('CPU', 'GPU'):
                if s not in chosen:
                    continue
                metric = {'game': {'CPU': 'game_1080p', 'GPU': 'raster_1080p'}, 'office': {'CPU': 'single_thread'},
                          'creation': {'CPU': 'blender', 'GPU': 'blender'}}[rec['values']['purpose']][s]
                row = benchmarks[chosen[s].product_key]
                rec['benchmarks'][s] = {'metric': metric, 'value': row[metric], 'derived': row.get('derived', {}).get(metric)}
            signature = {'identity': rec['build_identity'], 'totals': flow.build.totals,
                         'eligibility': flow.build.eligibility, 'verification': rec['verification'],
                         'rankings': {s: [{k: c.get(k) for k in ('product_key', 'purchase_qty', 'rank', 'score', 'breakdown')}
                                          for c in info['pool']] for s, info in sorted(flow.rank.slots.items())}}
            rec['signature_sha256'] = digest(signature)
            rec['rankings_sha256'] = digest(signature['rankings'])
        except Exception as exc:
            rec['engine_ms'] = (time.perf_counter_ns()-started)/1e6
            rec['error'] = compare._error(exc)
        rec['search_ms'] = math.fsum(t['elapsed_ms'] for t in search_trace)
        rec['stage4_ms'] = math.fsum(stage4_trace)
        rec['search_calls'] = search_trace
        records.append(rec)
        with (args.out/'records.jsonl').open('a') as stream:
            stream.write(json.dumps(rec, ensure_ascii=False, allow_nan=False)+'\n')
        return rec
    with patch.object(review_ranking, 'load_review_aspect_snapshot', frozen_review), \
            patch('src.db.get_conn', no_io), patch('psycopg.connect', no_io), patch('socket.socket.connect', no_io):
        for repeat in range(repeats):
            for i, request in enumerate(normal if repeat % 2 == 0 else list(reversed(normal))):
                execute(request, 'repeat', repeat)
                if (i+1) % 12 == 0 or i+1 == len(normal):
                    print(f'repeat {repeat+1}/{repeats}: {i+1}/{len(normal)}', flush=True)
        for suite, cases in (('cheapest', normal), ('extreme', extremes)):
            for i, request in enumerate(cases):
                execute(request, suite)
                if (i+1) % 12 == 0 or i+1 == len(cases):
                    print(f'{suite}: {i+1}/{len(cases)}', flush=True)
    assert before == {str(p.relative_to(ROOT)): experiment.sha(p) for p in tracked}
    repeated = {r['id']: [z for z in records if z['suite'] == 'repeat' and z['id'] == r['id']] for r in normal}
    service = {i: sorted(rs, key=lambda r: r['repeat_index'])[0] for i, rs in repeated.items()}
    cheapest = {r['id']: r for r in records if r['suite'] == 'cheapest'}
    def good(r):
        return 'error' not in r and r['minimum']['status'] == 'pass' and r['build']['eligibility']['status'] == 'recommendable' and all(v['passed'] for v in r['verification'])
    paired = {i for i in service if good(service[i]) and good(cheapest[i])}
    repeat_rows = [r for r in records if r['suite'] == 'repeat']
    repeat_summary = {'unique_requests': len(normal), 'repetitions': repeats, 'executions': len(repeat_rows),
        'stable_full_result_requests': sum(len({r.get('signature_sha256', digest(r.get('error'))) for r in rs}) == 1 for rs in repeated.values()),
        'stable_rankings_requests': sum(len({r.get('rankings_sha256') for r in rs}) == 1 for rs in repeated.values()),
        'errors': [r for r in repeat_rows if 'error' in r],
        'engine_ms': distribution([r['engine_ms'] for r in repeat_rows]),
        'search_ms': distribution([r['search_ms'] for r in repeat_rows]),
        'stage4_ms': distribution([r['stage4_ms'] for r in repeat_rows]),
        'per_input_engine_time_std_ms': distribution([statistics.pstdev(r['engine_ms'] for r in rs) for rs in repeated.values()]),
        'per_input_search_time_std_ms': distribution([statistics.pstdev(r['search_ms'] for r in rs) for rs in repeated.values()])}
    cells = []
    for p in experiment.MINIMUM:
        for b in (1000000, 2000000, 3500000):
            selected = [r for r in repeat_rows if r['values']['purpose'] == p and r['values']['budget_max'] == b]
            if selected:
                cells.append({'purpose': p, 'budget': b, 'executions': len(selected),
                              'engine_ms': distribution([r['engine_ms'] for r in selected]),
                              'search_ms': distribution([r['search_ms'] for r in selected])})
    extremities = []
    for p in experiment.MINIMUM:
        for b in EXTREME_BUDGETS:
            group = [r for r in records if r['suite'] == 'extreme' and r['values']['purpose'] == p and r['values']['budget_max'] == b]
            if not group:
                continue
            extremities.append({'purpose': p, 'budget': b, 'executions': len(group),
                'outcomes': dict(Counter(r['error']['type'] if 'error' in r else r['build']['eligibility']['status'] for r in group)),
                'engine_ms': distribution([r['engine_ms'] for r in group]),
                'search_ms': distribution([r['search_ms'] for r in group]),
                'prices': [r['build']['totals']['price'] for r in group if 'error' not in r],
                'minimum_pass': sum(r.get('minimum', {}).get('status') == 'pass' for r in group),
                'search_caps': sum(any(t.get('counts', {}).get('capped') for t in r['search_calls']) for r in group)})
    price_proofs = [r for r in cheapest.values() if 'error' not in r and r['search_calls'] and
                    all(t['counts']['global_minimum_proven'] for t in r['search_calls']) and
                    r['search_calls'][0]['selected_price'] == r['build']['totals']['price']]
    summary = {'generated_at': datetime.now(timezone.utc).isoformat(), 'input_hashes_unchanged': True,
        'total_engine_executions': len(records), 'repeat': repeat_summary, 'timing_cells': cells,
        'price_baseline': {'paired_recommendable_requests': len(paired), 'paired_ids': sorted(paired),
            'price_minimum_proven_requests': len(price_proofs), 'executions': len(cheapest),
            'service': experiment.pair_comparison(cheapest, service, paired),
            'cheapest': experiment.pair_comparison(cheapest, cheapest, paired),
            'minimum_pass': sum(r.get('minimum', {}).get('status') == 'pass' for r in cheapest.values()),
            'recommendable': sum(good(r) for r in cheapest.values()),
            'errors': [{'id': r['id'], 'error': r['error']} for r in cheapest.values() if 'error' in r]},
        'extreme': extremities, 'timeouts': sum(r.get('error', {}).get('type') == 'MeasurementTimeout' for r in records),
        'api_calls': 0, 'database_calls': 0, 'runtime_policy_changes': 0,
        'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                        'numpy': importlib.metadata.version('numpy'), 'logical_cpus': os.cpu_count(),
                        'cpu': next(line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),
                        'memory_total_kib': int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')))}}
    experiment.write(args.out/'summary.json', summary)
    experiment.write(args.out/'manifest.json', {'files_sha256': {str(p.relative_to(args.out)): experiment.sha(p) for p in sorted(args.out.rglob('*')) if p.is_file()}, 'input_sha256': before})
    print(json.dumps({'out': str(args.out), 'executions': len(records), 'stable_requests': repeat_summary['stable_full_result_requests'],
                      'price_minimum_proven': len(price_proofs), 'paired': len(paired), 'timeouts': summary['timeouts']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
