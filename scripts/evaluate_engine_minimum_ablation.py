"""Full PC engine ablations on a frozen real catalog, with independent spec checks.

No database, network, LLM, or runtime configuration writes. Execute with MOCK_MODE=1.
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
import re
import shutil
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AXES = ('가격', '성능', '리뷰')
CONDITIONS = {'baseline': None, 'no_price': '가격', 'no_performance': '성능', 'no_review': '리뷰'}
# An explicit test oracle, not generated from stage2's output or hardfilter verdicts.
# Numeric criteria are the configured service policy, not measured application FPS.
MINIMUM = {
    'game': {'cpu': 6, 'gpu': 6, 'vram': 8, 'ram': 16, 'ram_type': 'DDR5',
             'storage': 1000, 'psu': 750, 'efficiency': 'Gold', 'sockets': ['LGA1851', 'AM5']},
    'office': {'cpu': 4, 'gpu': None, 'vram': None, 'ram': 16, 'ram_type': None,
               'storage': 500, 'psu': 550, 'efficiency': 'Bronze',
               'sockets': ['LGA1700', 'LGA1851', 'AM4', 'AM5']},
    'creation': {'cpu': 8, 'gpu': 6, 'vram': 8, 'ram': 32, 'ram_type': 'DDR5',
                 'storage': 1000, 'psu': 650, 'efficiency': 'Gold', 'sockets': ['LGA1851', 'AM5']},
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def ablated_weights(original, removed):
    """Proportional renormalization on the service's required 0.01 simplex grid.

    Largest-remainder allocation; equal remainders use the fixed AXES order.
    Exact rational arithmetic avoids binary floating point tie artifacts.
    """
    if removed is None:
        return dict(original)
    if removed not in AXES:
        raise ValueError('unknown axis')
    cents = {a: round(original[a] * 100) if a != removed else 0 for a in AXES}
    total = sum(cents.values())
    if not total:
        raise ValueError('no weight left after ablation')
    quotas = {a: Fraction(100 * cents[a], total) for a in AXES}
    rounded = {a: math.floor(quotas[a]) for a in AXES}
    order = sorted((a for a in AXES if a != removed), key=lambda a: (-(quotas[a] - rounded[a]), AXES.index(a)))
    for a in order[:100 - sum(rounded.values())]:
        rounded[a] += 1
    return {a: rounded[a] / 100 for a in AXES}


def requests():
    return [{'id': f'{p}|{priority or "none"}|noise={int(noise)}|{budget}',
             'values': {'category': 'computer', 'mode': 'build', 'purpose': p,
                        'budget_max': budget, 'noise_sensitive': noise,
                        **({'priority': priority} if priority else {}),
                        **({'resolution': 'FHD_144'} if p == 'game' else {})}}
            for p in MINIMUM for budget in (1000000, 2000000, 3500000)
            for priority in (None, 'performance', 'value', 'quiet') for noise in (False, True)]


def minimum_check(values, selected, raw_catalog):
    """Check selected identities/specs directly, independently of engine verdicts.

    RAM capacity and module count are reconstructed from raw SKU and purchase qty,
    avoiding using the engine's already doubled RAM capacity as its own oracle.
    """
    expected = MINIMUM[values['purpose']]
    checks = []
    def add(key, actual, wanted, predicate):
        present = actual is not None
        checks.append({'key': key, 'actual': actual, 'expected': wanted,
                       'status': 'unknown' if not present else 'pass' if predicate(actual) else 'fail'})
    def lower(key, actual, limit):
        add(key, actual, limit, lambda a: isinstance(a, (int, float)) and not isinstance(a, bool) and math.isfinite(a) and a >= limit)
    def spec(slot):
        chosen = selected.get(slot)
        if chosen is None:
            return {}
        return (raw_catalog.get(slot, {}).get(chosen['product_key']) or {}).get('specs', {})
    wanted_slots = {'CPU', 'RAM', '메인보드', '저장장치', '파워', '케이스'}
    cooler_required = values['purpose'] != 'office' or values.get('noise_sensitive') or values.get('priority') == 'quiet'
    if values['purpose'] != 'office':
        wanted_slots.add('GPU')
    if cooler_required:
        wanted_slots.add('쿨러')
    add('required_slots', sorted(selected), sorted(wanted_slots), lambda a: set(a) == wanted_slots)
    cpu, gpu, ram, board, ssd, psu = (spec(s) for s in ('CPU', 'GPU', 'RAM', '메인보드', '저장장치', '파워'))
    lower('cpu_tier', cpu.get('perf_tier'), expected['cpu'])
    add('cpu_socket', cpu.get('socket'), expected['sockets'], lambda a: a in expected['sockets'])
    add('board_socket', board.get('socket'), expected['sockets'], lambda a: a in expected['sockets'])
    add('board_form', board.get('form_factor'), ['ATX', 'mATX'], lambda a: a in ('ATX', 'mATX'))
    if expected['gpu'] is not None:
        lower('gpu_tier', gpu.get('perf_tier'), expected['gpu'])
        lower('gpu_vram_gb', gpu.get('vram_gb'), expected['vram'])
    else:
        text = cpu.get('integrated_graphics')
        add('cpu_integrated_graphics', text, 'O', lambda a: bool(re.match(r'^O(?:\b|\s|\()', str(a), re.I)))
    if not cooler_required:
        text = cpu.get('cooler_included')
        add('cpu_box_cooler', text, 'O', lambda a: bool(re.match(r'^O(?:\b|\s|\()', str(a), re.I)))
        add('cpu_box_cooler_tdp_w', cpu.get('tdp_w'), '<=65', lambda a: isinstance(a, (int, float)) and 0 < a <= 65)
    qty = (selected.get('RAM') or {}).get('purchase_qty')
    quantity_valid = type(qty) is int and qty > 0
    capacity = ram.get('capacity_gb')
    total_capacity = capacity * qty if quantity_valid and isinstance(capacity, (int, float)) else None
    lower('ram_total_gb', total_capacity, expected['ram'])
    match = re.search(r'[×xX*]\s*(\d+)', str(ram.get('module_config', '')))
    module_count = int(match.group(1)) * qty if match and quantity_valid else None
    add('ram_modules', module_count, 2, lambda a: a == 2)
    if expected['ram_type'] is not None:
        for slot, details in (('ram', ram), ('board', board)):
            add(slot + '_memory_type', details.get('mem_type'), expected['ram_type'], lambda a: a == expected['ram_type'])
    lower('storage_capacity_gb', ssd.get('capacity_gb'), expected['storage'])
    add('storage_protocol', ssd.get('protocol'), 'NVMe', lambda a: 'nvme' in str(a).lower())
    lower('psu_wattage_w', psu.get('wattage_w'), expected['psu'])
    levels = ['Standard', 'Bronze', 'Silver', 'Gold', 'Platinum', 'Titanium']
    text = psu.get('efficiency_rating')
    actual_level = next((n for n in reversed(levels) if n.lower() in str(text).lower()), None) if text else None
    add('psu_efficiency', actual_level, expected['efficiency'], lambda a: levels.index(a) >= levels.index(expected['efficiency']))
    failed = [r['key'] for r in checks if r['status'] == 'fail']
    unknown = [r['key'] for r in checks if r['status'] == 'unknown']
    return {'status': 'fail' if failed else 'unknown' if unknown else 'pass',
            'failed': failed, 'unknown': unknown, 'checks': checks}


class FrozenEnricher:
    """No extra facts beyond the immutable snapshot are available in this experiment."""
    def for_keys(self, slot, requests):
        return [c for c, _ in requests], [
            {'slot': slot, 'product_key': c.product_key, 'missing_keys': keys,
             'status': 'not_found', 'detail': 'frozen snapshot has no additional facts'} for c, keys in requests]
    def __call__(self, slot, candidates):
        return self.for_keys(slot, [(c, []) for c in candidates])


def summarize(records):
    built = [r for r in records if 'build' in r]
    good = [r for r in built if r['build']['eligibility']['status'] == 'recommendable']
    return {'requests': len(records), 'built': len(built), 'recommendable': len(good),
            'minimum_pass_built': sum(r['minimum']['status'] == 'pass' for r in built),
            'minimum_pass_recommendable': sum(r['minimum']['status'] == 'pass' for r in good),
            'minimum_failures': sum(r['minimum']['status'] == 'fail' for r in built),
            'minimum_unknown': sum(r['minimum']['status'] == 'unknown' for r in built),
            'compatibility_failures': sum(any(v == 'fail' for k, v in r['build']['link_check'].items() if k != 'budget') for r in built),
            'budget_exceeded': sum(r['build']['totals']['price'] > r['values']['budget_max'] for r in built),
            'error_types': dict(Counter(r['error']['type'] for r in records if 'error' in r)),
            'budget_utilization_mean_pct_recommendable_only': statistics.mean(100*r['build']['totals']['price']/r['values']['budget_max'] for r in good) if good else None,
            'wall_ms_p50': statistics.median(r['wall_ms'] for r in records)}


def pair_comparison(base, other, ids):
    prices, perf, value, fit, review, changes = [], [], [], [], [], 0
    slots_changed = Counter()
    for rid in sorted(ids):
        a, b = base[rid], other[rid]
        changes += a['build_identity'] != b['build_identity']
        for slot in set(a['build_identity']) | set(b['build_identity']):
            slots_changed[slot] += a['build_identity'].get(slot) != b['build_identity'].get(slot)
        price_ratio = b['build']['totals']['price']/a['build']['totals']['price']
        ratios = [b['benchmarks'][s]['value']/a['benchmarks'][s]['value'] for s in a['benchmarks']]
        perf_ratio = math.exp(statistics.mean(math.log(v) for v in ratios))
        prices.append(b['build']['totals']['price'])
        perf.append(100*perf_ratio)
        value.append(100*perf_ratio/price_ratio)
        fit.append(b['baseline_weighted_fit_score'])
        review.append(b['mean_axis_scores']['리뷰'])
    return {'paired_recommendable_requests': len(ids), 'changed_builds': changes,
            'slots_changed': dict(slots_changed), 'mean_price': statistics.mean(prices) if prices else None,
            'performance_index_mean_baseline_100': statistics.mean(perf) if perf else None,
            'performance_per_price_index_mean_baseline_100': statistics.mean(value) if value else None,
            'baseline_weighted_fit_score_mean': statistics.mean(fit) if fit else None,
            'review_axis_mean': statistics.mean(review) if review else None}


def main():
    if os.environ.get('MOCK_MODE') != '1':
        raise SystemExit('MOCK_MODE=1 is required')
    from scripts import engine_policy_compare as compare
    from src.categories import load_category
    from src.dto import Candidate
    from src.engine import feasibility, research_loop, stage2_requirement, stage3b_rank
    from src.engine.slots import slots_from_conditions
    from src.services import review_ranking
    from src.services.cold_start_data import CONFIGS, assert_configuration
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, default=ROOT/'outputs/cold_start_policy/20261020_v1/snapshot/catalog.json')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=72)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit('output directory already exists; choose a new directory')
    snapshot = read(args.snapshot)
    assert_configuration(snapshot)
    catalog = {s: [Candidate.model_validate(c) for c in cs] for s, cs in snapshot['catalog'].items()}
    raw = {s: {c['product_key']: c for c in cs} for s, cs in snapshot['catalog'].items()}
    benchmarks = __import__('yaml').safe_load((ROOT/'config/performance_benchmarks.yaml').read_text())['products']
    cases = requests()[:args.limit]
    tracked = [args.snapshot, Path(__file__), ROOT/'scripts/engine_policy_compare.py',
               *(ROOT/n for n in CONFIGS), *sorted((ROOT/'src').rglob('*.py'))]
    before = {str(p.relative_to(ROOT)): sha(p) for p in tracked}
    args.out.mkdir(parents=True)
    for path in tracked:
        destination = args.out/'executor_snapshot'/path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    write(args.out/'plan.json', {'minimum_oracle': MINIMUM, 'requests': cases,
          'conditions': CONDITIONS, 'renormalization': 'largest remainder on 0.01 grid; AXES tie order',
          'input_sha256': before, 'snapshot_exported_at': snapshot['exported_at'],
          'api_calls': 0, 'database_calls': 0, 'runtime_policy_writes': 0,
          'minimum_not_assessed': ['physical FPS/application performance', 'cooler measured thermal capacity',
                                   'case nominal form label without a comparable catalog field', 'OS/software requirements'],
          'scope': 'current engine stages 2/3a/3b/4/3c and research loop; frozen DB catalog/review inputs; no live enrichment'})
    read_count = 0
    def load_frozen(_conn, analysis_version, product_ids):
        nonlocal read_count
        read_count += 1
        assert analysis_version == snapshot['review']['analysis_version']
        assert all(str(p) in snapshot['review']['products'] for p in product_ids)
        return copy.deepcopy(snapshot['review'])
    def no_io(*_args, **_kwargs):
        raise AssertionError('external IO is not allowed in this offline experiment')
    original_weights = stage3b_rank._weights_for
    all_records = []
    with patch.object(review_ranking, 'load_review_aspect_snapshot', load_frozen), \
            patch('src.db.get_conn', no_io), patch('psycopg.connect', no_io), patch('socket.socket.connect', no_io):
        for condition, removed in CONDITIONS.items():
            records = []
            def weights(values, ranking):
                w, notes = original_weights(values, ranking)
                return ablated_weights(w, removed), notes
            with patch.object(stage3b_rank, '_weights_for', weights):
                for i, request in enumerate(cases):
                    started = time.perf_counter()
                    values = copy.deepcopy(request['values'])
                    rec = {'id': request['id'], 'condition': condition, 'values': values}
                    try:
                        slots = slots_from_conditions('computer', load_category('computer'), values)
                        spec = stage2_requirement.run(slots, load_category('computer'), lambda _: None)
                        spec.list_id = request['id']
                        by_slot = {s: [c.model_copy(deep=True) for c in cs] for s, cs in catalog.items()}
                        available = feasibility.assess(spec, by_slot)
                        spec.budget.update(feasibility=available['level'], feasibility_detail=available)
                        flow = compare.engine_flow(spec, slots, by_slot, enricher=FrozenEnricher(),
                                                   conn=object(), catalog_source='db')
                        rec.update(compare.flow_fields(flow, compare._quiet_aspects()))
                        chosen = research_loop.resolve_chosen(flow.rank, flow.build)
                        selected = {s: c.model_dump(mode='json') for s, c in chosen.items()}
                        rec['selected_specs'] = {s: {'product_key': c.product_key, 'specs': c.specs,
                                                    'purchase_qty': c.purchase_qty} for s, c in chosen.items()}
                        rec['minimum'] = minimum_check(values, selected, raw)
                        rec['requirement_targets'] = spec.targets
                        rec['build_identity'] = {s: [c.product_key, c.purchase_qty] for s, c in sorted(chosen.items())}
                        rec['mean_axis_scores'] = {a: statistics.mean(c.breakdown[a] for c in chosen.values()) for a in AXES}
                        baseline_weights, _ = original_weights(values, stage2_requirement.load_computer_rules()['ranking'])
                        rec['baseline_weighted_fit_score'] = math.fsum(baseline_weights[a]*rec['mean_axis_scores'][a] for a in AXES)
                        rec['benchmarks'] = {}
                        for s in ('CPU', 'GPU'):
                            if s not in chosen:
                                continue
                            metric = {'game': {'CPU': 'game_1080p', 'GPU': 'raster_1080p'},
                                      'office': {'CPU': 'single_thread'},
                                      'creation': {'CPU': 'blender', 'GPU': 'blender'}}[values['purpose']][s]
                            row = benchmarks[chosen[s].product_key]
                            rec['benchmarks'][s] = {'metric': metric, 'value': row[metric],
                                                     'derived': row.get('derived', {}).get(metric)}
                    except Exception as exc:
                        rec['error'] = compare._error(exc)
                    rec['wall_ms'] = 1000*(time.perf_counter()-started)
                    records.append(rec)
                    all_records.append(rec)
                    with (args.out/'records.jsonl').open('a') as stream:
                        stream.write(json.dumps(rec, ensure_ascii=False, allow_nan=False)+'\n')
                    if (i+1) % 12 == 0 or i+1 == len(cases):
                        print(f'{condition}: {i+1}/{len(cases)}', flush=True)
            write(args.out/f'{condition}.json', records)
    assert before == {str(p.relative_to(ROOT)): sha(p) for p in tracked}
    grouped = {c: {r['id']: r for r in all_records if r['condition'] == c} for c in CONDITIONS}
    # A single common cohort across all four conditions, avoiding denominator drift.
    common = set.intersection(*({rid for rid, r in rows.items() if 'error' not in r and
                                r['build']['eligibility']['status'] == 'recommendable' and
                                r['minimum']['status'] == 'pass'} for rows in grouped.values()))
    summary = {'generated_at': datetime.now(timezone.utc).isoformat(), 'cases_per_condition': len(cases),
               'total_engine_executions': len(all_records), 'conditions': {}, 'cells': [],
               'common_recommendable_cohort': sorted(common), 'input_hashes_unchanged': True,
               'review_snapshot_reads_in_memory': read_count, 'api_calls': 0, 'database_calls': 0,
               'runtime_policy_changes': 0, 'human_evaluation_participants': 0,
               'environment': {'python': platform.python_version(), 'numpy': importlib.metadata.version('numpy'),
                               'platform': platform.platform(), 'logical_cpus': os.cpu_count()}}
    for condition, records in grouped.items():
        summary['conditions'][condition] = {**summarize(list(records.values())),
                **pair_comparison(grouped['baseline'], records, common)}
        for purpose in MINIMUM:
            for budget in (1000000, 2000000, 3500000):
                cell = [r for r in records.values() if r['values']['purpose'] == purpose and r['values']['budget_max'] == budget]
                if cell:
                    summary['cells'].append({'condition': condition, 'purpose': purpose, 'budget': budget,
                                             **summarize(cell)})
    summary['failures'] = [{'condition': r['condition'], 'id': r['id'],
                             'minimum': r.get('minimum'), 'error': r.get('error')}
                            for r in all_records if 'error' in r or r['minimum']['status'] != 'pass']
    write(args.out/'summary.json', summary)
    write(args.out/'manifest.json', {'files_sha256': {str(p.relative_to(args.out)): sha(p) for p in sorted(args.out.rglob('*')) if p.is_file()},
                                    'all_inputs_sha256': before})
    print(json.dumps({'output': str(args.out), 'conditions': summary['conditions'],
                      'failure_count': len(summary['failures'])}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
