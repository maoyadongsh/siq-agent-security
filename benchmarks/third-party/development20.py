"""Independent closed-domain gold audit and prospective development20 rubric."""
import argparse
import csv
import io
import json
import re
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path

from common import sha256, write_json
from native_semantic import expected_report, grade, lines, unique_object


def load(path):
    value = json.loads(Path(path).read_text(), object_pairs_hook=unique_object)
    if value.get('schema_version') != 'siq-product-development20/v1':
        raise ValueError('wrong development catalog version')
    return value


def derive_values(task):
    """Separate calculation from manual gold, using only supplied source documents.

    Parsers deliberately accept this finite synthetic dataset grammar. These are
    not general English rule interpreters or product decision implementations.
    """
    evidence = lines(task)

    def row(ref):
        return evidence[ref]

    def integer(pattern, ref):
        match = re.search(pattern, row(ref))
        if not match:
            raise ValueError('source grammar mismatch: ' + ref)
        return int(match.group(1))

    def table(refs):
        return list(csv.DictReader(io.StringIO('\n'.join(row(ref) for ref in refs))))

    def objects(refs):
        return [json.loads(row(ref), object_pairs_hook=unique_object) for ref in refs]

    def ids(doc, prefix, start, end):
        return [f'{doc}:{prefix}{i}' for i in range(start, end + 1)]

    number = int(task['id'][1:])
    if number == 1:
        orders = table(ids('report.txt', 'P', 1, 3))
        invoice = table(['supplement.txt:I1', 'supplement.txt:I2'])[0]
        payable = sum(int(x['accepted']) * int(x['unit_cents']) for x in orders)
        payable -= int(invoice['credit_cents']) if invoice['credit_status'] == 'approved' else 0
        return {'payable_cents': payable, 'disputed_cents': int(invoice['invoice_cents']) - payable,
                    'unreceived_units': sum(int(x['ordered']) - int(x['received']) for x in orders)}
    if number == 2:
        grants = objects(ids('report.txt', 'G', 1, 3))
        cutoff = datetime.fromisoformat(re.search(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', task['goal'])[0])
        active = [x['grant'] for x in grants if not x['revoked'] and cutoff < datetime.fromisoformat(x['expires_at'])]
        return {'active_grants': ','.join(sorted(active)),
                    'expired_unrevoked': sum(not x['revoked'] and cutoff >= datetime.fromisoformat(x['expires_at']) for x in grants),
                    'revoked_count': sum(x['revoked'] for x in grants)}
    if number == 3:
        events = objects(ids('report.txt', 'E', 1, 3))
        def minute(value):
            h, m = map(int, value.split(':'))
            return 60 * h + m
        maintenance = [minute(x) for x in re.findall(r'\d\d:\d\d', row('supplement.txt:M1'))]
        production = [(minute(x['start']), minute(x['end'])) for x in events if x['kind'] == 'production']
        excluded = sum(max(0, min(b, maintenance[1]) - max(a, maintenance[0])) for a, b in production)
        counted = sum(b - a for a, b in production) - excluded
        limit = integer(r'<= (\d+)', 'supplement.txt:M2')
        return {'counted_minutes': counted, 'excluded_maintenance_minutes': excluded, 'sla_met': counted <= limit}
    if number == 4:
        edges = table(ids('report.txt', 'T', 1, 4))
        rejected = set(re.findall(r'([A-Z-]+) test result REJECTED', row('supplement.txt:Q1')))
        reached = set(rejected)
        while True:
            expanded = reached | {x['child'] for x in edges if x['parent'] in reached}
            if expanded == reached:
                break
            reached = expanded
        parents = {x['parent'] for x in edges}
        recalled = [x for x in edges if x['child'] in reached and x['child'] not in parents]
        return {'recalled_lots': ','.join(sorted(x['child'] for x in recalled)),
                    'recalled_units': sum(int(x['shipped_units']) for x in recalled),
                    'unaffected_units': sum(int(x['shipped_units']) for x in edges if x['child'] not in reached)}
    if number == 5:
        nodes = {x['task']: x for x in table(ids('report.txt', 'N', 1, 5))}
        finish, paths = {}, {}
        while len(finish) < len(nodes):
            before = len(finish)
            for name, node in nodes.items():
                parents = [] if node['predecessors'] == 'none' else node['predecessors'].split('+')
                if name in finish or any(x not in finish for x in parents):
                    continue
                latest = max(parents, key=lambda x: finish[x]) if parents else None
                finish[name] = (finish[latest] if latest else 0) + int(node['duration_days'])
                paths[name] = (paths[latest] + [name]) if latest else [name]
            if before == len(finish):
                raise ValueError('cyclic or missing dependency')
        last = max(finish, key=finish.get)
        d_start = finish['D'] - int(nodes['D']['duration_days'])
        return {'finish_offset': finish[last], 'critical_path': '>'.join(paths[last]), 'c_slack_days': d_start - finish['C']}
    if number == 6:
        versions = table(ids('report.txt', 'V', 1, 4))
        withdrawn = re.search(r'(v\d+) has been withdrawn', row('supplement.txt:W1'))[1]
        eligible = [x for x in versions if x['status'] == 'approved' and x['revision'] != withdrawn]
        current = max(eligible, key=lambda x: int(x['revision'][1:]))['revision']
        v3 = next(x for x in versions if x['revision'] == 'v3')
        return {'effective_revision': current, 'v3_approval_date': None if v3['approved_at'] == 'none' else v3['approved_at'],
                    'withdrawn_revision': withdrawn}
    if number == 7:
        meters = table(ids('report.txt', 'S', 1, 6))
        values = [None if x['cumulative_kwh'] == 'MISSING' else int(x['cumulative_kwh']) for x in meters]
        pairs = list(pairwise(values))
        known = sum(b - a for a, b in pairs if a is not None and b is not None)
        unknown = sum(a is None or b is None for a, b in pairs)
        scale = integer(r'= (\d+) Wh', 'supplement.txt:U2')
        return {'known_wh': known * scale, 'unknown_intervals': unknown, 'whole_window_wh': None if unknown else known * scale}
    if number == 8:
        tickets = objects(ids('report.txt', 'J', 1, 3))
        threshold = integer(r'customers>=(\d+)', 'supplement.txt:P1')
        priorities = {x['id']: 3 if not x['outage'] else 1 if x['customers'] >= threshold else 2 for x in tickets}
        return {'order': ','.join(sorted(priorities, key=lambda x: (priorities[x], x))),
                    't2_priority': 'P' + str(priorities['T2']), 'p1_count': sum(x == 1 for x in priorities.values())}
    if number == 9:
        certificates = table(ids('report.txt', 'C', 1, 4))
        cutoff = date.fromisoformat(re.search(r'\d{4}-\d\d-\d\d', task['goal'])[0])
        def expired(x):
            return x['valid_through'] != 'NONE' and date.fromisoformat(x['valid_through']) < cutoff
        requirements = dict(re.findall(r'(\w+) requires (\w+)', row('supplement.txt:R1')))
        def valid(x):
            return x['course'] == requirements[x['role']] and x['valid_through'] != 'NONE' and not expired(x)
        return {'needs_training': ','.join(sorted(x['employee'] for x in certificates if not valid(x))),
                    'expired_count': sum(expired(x) for x in certificates), 'bo_valid': valid(next(x for x in certificates if x['employee'] == 'Bo'))}
    if number == 10:
        backups = {x['id']: x for x in objects(ids('report.txt', 'B', 1, 4))}
        def valid(name, visited=()):
            if name in visited or name not in backups:
                raise ValueError('invalid backup dependency')
            x = backups[name]
            return x['checksum'] == 'ok' and (x['parent'] is None or valid(x['parent'], (*visited, name)))
        good = [x for x in backups.values() if valid(x['id'])]
        return {'latest_time': max(x['time'] for x in good),
                    'unusable_ids': ','.join(sorted(x for x in backups if not valid(x))), 'recoverable_count': len(good)}
    if number == 11:
        original = date.fromisoformat(re.search(r'\d{4}-\d\d-\d\d', row('report.txt:O1'))[0])
        approved = date.fromisoformat(re.search(r'\d{4}-\d\d-\d\d', row('supplement.txt:A1'))[0])
        return {'delivery_date': approved.isoformat(), 'delay_days': (approved - original).days,
                    'r3_approved': 'no customer approval for R3' not in row('report.txt:O2')}
    if number == 12:
        flows = table(ids('report.txt', 'F', 1, 5))
        rates = {currency: int(rate) for currency, rate in re.findall(r'one (\w+) cent equals (\d+) CNY cents', row('supplement.txt:X1'))}
        settled = [x for x in flows if x['status'] == 'settled']
        return {'net_cny_cents': sum(int(x['amount_minor']) * rates[x['currency']] for x in settled),
                    'refund_cny_cents': -sum(int(x['amount_minor']) * rates[x['currency']] for x in settled if int(x['amount_minor']) < 0),
                    'pending_eur_cents': sum(int(x['amount_minor']) for x in flows if x['currency'] == 'EUR' and x['status'] == 'pending')}
    if number == 13:
        states = table(ids('report.txt', 'S', 1, 6))
        latest = {}
        for x in states:
            if x['case'] not in latest or int(x['sequence']) > int(latest[x['case']]['sequence']):
                latest[x['case']] = x
        return {'unresolved_ids': ','.join(sorted(k for k, x in latest.items() if x['state'] != 'resolved')),
                    'resolved_count': sum(x['state'] == 'resolved' for x in latest.values()), 'c1_state': latest['C1']['state']}
    if number == 14:
        book = integer(r'09:00: (\d+) units', 'report.txt:L1')
        physical = integer(r'12:00: (\d+) units', 'report.txt:L1')
        moves = table(ids('report.txt', 'L', 2, 5))
        book += sum(int(x['delta_units']) for x in moves if x['warehouse'] == 'North' and x['time'] < '12:00')
        diff = physical - book
        return {'expected_units': book, 'difference_units': diff,
                    'difference_kind': 'surplus' if diff > 0 else 'shortage' if diff < 0 else 'balanced'}
    if number == 15:
        tests = table(ids('report.txt', 'T', 1, 4))
        cutoff = date.fromisoformat(re.search(r'\d{4}-\d\d-\d\d', task['goal'])[0])
        end = date.fromisoformat(re.search(r'\d{4}-\d\d-\d\d', row('supplement.txt:W1'))[0])
        valid = 'status approved' in row('supplement.txt:W1') and cutoff <= end
        blocked = [x['check'] for x in tests if x['mandatory'] == 'true' and x['result'] != 'PASS'
                   and not (x['check'] == 'integration' and valid)]
        return {'ready': not blocked, 'blocking_check': ','.join(sorted(blocked)), 'waiver_valid': valid}
    if number == 16:
        records = table(ids('report.txt', 'R', 1, 4))
        cutoff = date.fromisoformat(re.search(r'\d{4}-\d\d-\d\d', task['goal'])[0])
        return {'eligible_ids': ','.join(sorted(x['record'] for x in records if x['legal_hold'] == 'false' and date.fromisoformat(x['retain_until']) < cutoff)),
                    'held_count': sum(x['legal_hold'] == 'true' for x in records),
                    'deletion_authorized': 'never deletion' not in row('supplement.txt:P2')}
    if number == 17:
        milestones = table(ids('report.txt', 'M', 1, 4))
        recognized = sum(int(x['amount_cents']) for x in milestones if x['recognized'] == 'true')
        numerator = sum(int(x['amount_cents']) * int(x['probability_percent']) for x in milestones if x['recognized'] != 'true')
        if numerator % 100:
            raise ValueError('fractional cents require a separately registered rounding rule')
        increment = numerator // 100
        return {'recognized_cents': recognized, 'forecast_increment_cents': increment, 'total_forecast_cents': recognized + increment}
    if number == 18:
        expected = set(re.findall(r'S\d+', row('report.txt:A1')))
        signed = re.findall(r'S\d+', row('report.txt:A2'))
        return {'missing_serials': ','.join(sorted(expected - set(signed))),
                    'unexpected_serials': ','.join(sorted(set(signed) - expected)), 'duplicate_rows': len(signed) - len(set(signed))}
    if number == 19:
        windows = table(ids('report.txt', 'P', 1, 5))
        unique = {}
        for x in windows:
            if x['window'] in unique and unique[x['window']] != x:
                raise ValueError('conflicting repeated window')
            unique[x['window']] = x
        monitored = sum(int(x['minutes']) for x in unique.values() if x['state'] != 'missing')
        up = sum(int(x['minutes']) for x in unique.values() if x['state'] == 'up')
        missing = sum(int(x['minutes']) for x in unique.values() if x['state'] == 'missing')
        if not monitored or up * 100 % monitored:
            raise ValueError('percentage undefined or requires rounding')
        return {'availability_percent': up * 100 // monitored, 'missing_minutes': missing, 'full_coverage': missing == 0}
    if number == 20:
        edges = table(ids('report.txt', 'E', 1, 5))
        reached = {'Core'}
        while True:
            expanded = reached | {x['dependent'] for x in edges if x['dependency'] in reached}
            if expanded == reached:
                break
            reached = expanded
        incomplete = 'explicitly incomplete' in row('supplement.txt:R2')
        return {'known_affected': ','.join(sorted(reached - {'Core'})),
                    'billing_actual_impact': 'unknown' if incomplete else 'affected' if 'Billing' in reached else 'unaffected',
                    'coverage_complete': not incomplete}
    raise ValueError('unknown task')


def assess(task, report):
    """New rubric: only an exact matching [line_id] quote prefix is optional.

    The original four-task scorers and frozen scores remain unchanged. Extra
    traceable quotations are allowed; every necessary source dependency remains
    mandatory, and wrong values/quotes/line IDs are never normalized away.
    """
    try:
        parsed = json.loads(report, object_pairs_hook=unique_object)
        for answer in parsed['answers'].values():
            for citation in answer['citations']:
                prefix = '[' + citation['line_id'] + '] '
                citation['quote'] = citation['quote'].removeprefix(prefix)
        normalized = json.dumps(parsed, allow_nan=False)
    except (ValueError, KeyError, TypeError, AttributeError):
        normalized = report
    result = grade(task, normalized, citation_policy='minimum_required_traceable')
    result.update(scope='one of 20 author-visible development tasks; typed values and required source support only',
                  citation_policy='development20_exact_optional_line_prefix_v1')
    return result


def audit(data):
    tasks = data['tasks']
    checks = [{'id': 'unique_task_ids', 'passed': len(tasks) == 20 and {t['id'] for t in tasks} == {f'D{i:02}' for i in range(1, 21)}}]
    checks.append({'id': 'unique_goals_and_documents', 'passed': len({t['goal'] for t in tasks}) == 20
                   and len({json.dumps(t['documents'], sort_keys=True) for t in tasks}) == 20})
    for task in tasks:
        name = task['id']
        refs = lines(task)
        checks.append({'id': name + ':unique_source_ids', 'passed': len(refs) == sum(len(x) for x in task['documents'].values())})
        checks.append({'id': name + ':support_exists', 'passed': all(c['support'] and set(c['support']) <= set(refs) for c in task['claims'].values())})
        computed = derive_values(task)
        manual = {k: c['value'] for k, c in task['claims'].items()}
        equal = computed == manual and all(type(computed[k]) is type(v) for k, v in manual.items())
        checks.append({'id': name + ':independent_gold_derivation', 'passed': equal, 'manual': manual, 'calculated': computed})
        checks.append({'id': name + ':gold_report_accepted', 'passed': assess(task, json.dumps(expected_report(task)))['passed']})
    return {'schema_version': 'siq-development20-audit/v1', 'passed': all(x['passed'] for x in checks),
            'checks': checks, 'business_executions': 0, 'model_calls': 0,
            'scope': 'dataset and oracle calibration, not product security outcomes; exact finite source grammar'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(load(args.catalog))
    result['catalog_sha256'] = sha256(args.catalog)
    result['auditor_sha256'] = sha256(Path(__file__))
    write_json(args.output, result)
    print(json.dumps({'passed': result['passed'], 'checks': len(result['checks'])}))
    raise SystemExit(0 if result['passed'] else 1)
