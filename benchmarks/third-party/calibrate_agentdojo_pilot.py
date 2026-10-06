"""Compare reference dispatch with upstream; never a model outcome."""
import argparse
import json
import re
import sys
from pathlib import Path

from adapters.agentdojo import make_runtime, serializable_messages
from common import Events, write_json


def equivalent_differences(diff):
    """Only wall-clock timestamps of inbox emails may vary between executions."""
    return not diff or (set(diff) == {'values_changed'} and all(
        re.fullmatch(r"root\['inbox'\]\['(?:emails|sent)'\]\[(?:'[^']+'|[0-9]+)\]\['timestamp'\]", path)
        for path in diff['values_changed']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    sys.path.insert(0, str(Path(protocol['upstream_root']) / 'src'))
    from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
    from agentdojo.functions_runtime import FunctionsRuntime
    from agentdojo.task_suite.load_suites import get_suite
    from agentdojo.task_suite.task_suite import (
        functions_stack_trace_from_messages,
        model_output_from_messages,
    )
    from deepdiff import DeepDiff

    args.out.mkdir(parents=True, exist_ok=False)
    suite = get_suite(protocol['benchmark_version'], protocol['suite'])
    rows = []
    for key in protocol['applicability']['selected_tasks']:
        task = suite.get_user_task_by_id(key)
        before = task.init_environment(suite.load_and_inject_default_environment({}))
        runtime, dispatches = make_runtime(suite.tools, None, Events(args.out / (key + '.jsonl'), key), protocol['exposed_tools'])
        wrapped = GroundTruthPipeline(task).query(task.PROMPT, runtime, before.model_copy(deep=True), [], {})
        original = GroundTruthPipeline(task).query(task.PROMPT, FunctionsRuntime(suite.tools), before.model_copy(deep=True), [], {})
        difference = json.loads(DeepDiff(wrapped[2].model_dump(mode='json'), original[2].model_dump(mode='json')).to_json())
        row = {'task_id': key, 'difference': difference,
               'environment_equal_except_inbox_wall_clock': equivalent_differences(difference),
               'transcript_equal': serializable_messages(wrapped[3]) == serializable_messages(original[3]),
               'dispatches_completed': bool(dispatches) and all(d['completed'] for d in dispatches),
               'reference_utility': suite._check_user_task_utility(task, model_output_from_messages(wrapped[3]), before, wrapped[2], functions_stack_trace_from_messages(wrapped[3]))}
        row['passed'] = all(row[k] for k in ('environment_equal_except_inbox_wall_clock', 'transcript_equal', 'dispatches_completed', 'reference_utility'))
        rows.append(row)
        write_json(args.out / (key + '.json'), {'wrapped_environment': wrapped[2].model_dump(mode='json'), 'original_environment': original[2].model_dump(mode='json'), 'wrapped_messages': serializable_messages(wrapped[3]), 'original_messages': serializable_messages(original[3])})
    report = {'tasks': rows, 'passed': sum(r['passed'] for r in rows), 'total': len(rows), 'model_calls': 0, 'scope': 'reference dispatch equivalence only; inbox wall-clock difference permitted, all other fields and complete transcript checked'}
    write_json(args.out / 'report.json', report)
    print(json.dumps({'passed': report['passed'], 'total': report['total']}))
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
