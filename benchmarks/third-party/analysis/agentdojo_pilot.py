"""Descriptive paired task outcomes; shared workspace means no IID inference."""
from collections import Counter


def paired(rows, left='B0', right='B2', condition='adversarial'):
    selected = {g: {r['task_id']: r for r in rows if r['group'] == g and r['condition'] == condition} for g in (left, right)}
    if set(selected[left]) != set(selected[right]):
        raise ValueError('paired comparison requires matching allocated task IDs')
    cells = {key: Counter() for key in ('utility_completed', 'harm_observed')}
    items = []
    label = {True: 'yes', False: 'no', None: 'unknown'}
    for task in sorted(selected[left]):
        a, b = selected[left][task], selected[right][task]
        item = {'task_id': task}
        for field, counter in cells.items():
            transition = label[a[field]] + '->' + label[b[field]]
            counter[transition] += 1
            item[field] = transition
        item['lab_boundary_intervened'] = {left: a['lab_boundary_intervened'], right: b['lab_boundary_intervened']}
        items.append(item)
    return {'left': left, 'right': right, 'condition': condition, 'task_blocks': len(items),
            'cells': {k: dict(v) for k, v in cells.items()}, 'tasks': items,
            'scope': 'descriptive paired task IDs only; shared entities and one fixed attack, no independence or confirmatory effect claim'}
