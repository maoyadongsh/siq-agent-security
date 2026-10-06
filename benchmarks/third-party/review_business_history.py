"""Read-only audit of local video-linked business evidence; not a new run."""
import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

from common import safe_path, sha256, utc_now, write_json


def review(campaign, video):
    candidate = campaign / 'private/candidates/5470ab3780f2-fixturefix2'
    spec = importlib.util.spec_from_file_location('history_receipts', candidate / 'benchmarks/runtime-security/evidence.py')
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    sources, cohorts = {}, {}
    for name in ('film-qwen', 'film-controls'):
        root = video / 'evidence' / name
        sums = json.loads((root / 'sha256.json').read_text())
        for relative, digest in sums.items():
            path = safe_path(root, relative)
            if sha256(path) != digest:
                raise ValueError('historical export changed')
            sources[str(path)] = digest
        bundle = json.loads((root / 'public-receipts.json').read_text())
        receipts, count = evidence.verify_receipt_bundles([bundle])
        snapshot = json.loads((root / 'snapshot.json').read_text())
        tasks, effects = [], 0
        for task in snapshot['tasks']:
            result = task.get('result')
            if result:
                for action in result.get('preparation', {}).get('actions', []) + result['task']['actions']:
                    signed = receipts[action['receipt_id']][0]
                    if (signed['action_id'], signed['action'], signed['reason_code']) != (action['action_id'], action['decision'], action['reason_code']):
                        raise ValueError('historical action/signature mismatch')
                    if action['effect']:
                        evidence.verify_effect_envelope(action['effect'], receipts)
                        effects += 1
            tasks.append({'task_id': task['id'], 'scenario': task['scenario'],
                          'status': (task.get('task') or {}).get('status'),
                          'calls': len(task.get('model_calls', [])),
                          'models': sorted({v['model'] for v in task.get('model_calls', [])}),
                          'received_messages': len(result['messages']) if result else None})
        cohorts[name] = {'verified_receipts': count, 'verified_effect_envelopes': effects,
                        'source_sha': snapshot['source_sha'], 'tasks': tasks,
                        'scope': 'entire historical service export; not all tasks appeared in film'}
    mp4 = video / 'output/full-v4/siq-agent-security-full-v4.mp4'
    metadata = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,width,height,r_frame_rate', '-of', 'json', str(mp4)], text=True))
    selected = ['output/full-v4/README.md', 'output/full-v4/script.zh-en.md',
                'output/full-v4/shot-evidence-index.json', 'output/full-v4/materials-manifest.json',
                'output/full-v4/contact-sheet.jpg', 'output/full-v4/siq-agent-security-full-v4.mp4',
                'src/full-v4/evidence.json',
                'workbuddy-windows/wb-20260927T154657Z-repair1-delivery-v2/files/wb-20260927T154657Z-repair1/experiment-report.md']
    for name in selected:
        sources[str(video / name)] = sha256(video / name)
    manifest = json.loads((video / 'output/full-v4/materials-manifest.json').read_text())
    mismatches = []
    for item in manifest['raw_assets']:
        path = safe_path(video, item['path'])
        if not path.is_file() or sha256(path) != item['sha256']:
            mismatches.append(item['path'])
    result = {'reviewed_at': utc_now(), 'relationship': 'author_readonly_historical_review',
              'sources': sources, 'video_metadata': metadata, 'historical_cohorts': cohorts,
              'raw_assets_checked': len(manifest['raw_assets']), 'raw_asset_mismatches': mismatches,
              'visual_review': 'existing V4 contact sheet and evidence-index chronology; no claim of full real-time viewing',
              'windows_scope': 'retained Windows WorkBuddy report and source index; not a new Windows execution or independent signature audit',
              'new_business_executions': 0}
    write_json(campaign / 'reports/historical-business-review-001.json', result)
    print(json.dumps({'cohorts': {k: {'receipts': v['verified_receipts'], 'effects': v['verified_effect_envelopes']} for k, v in cohorts.items()},
                      'raw_assets_checked': len(manifest['raw_assets']), 'mismatches': len(mismatches)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--video', type=Path, required=True)
    args = parser.parse_args()
    review(args.campaign.resolve(), args.video.resolve())
