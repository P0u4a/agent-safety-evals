"""Objective, pre-judging summary. Never labels refusal or deception from counts."""
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

from run_upward_documents import save


def analyze(root):
    config = json.loads((root / 'config.json').read_text())
    records = json.loads((root / 'main/completion.json').read_text())['results']
    groups = {}
    for outcome in [*config['environment']['targets'], 'choose']:
        a = [r for r in records if r['outcome'] == outcome and r['kind'] == 'agentic']
        l = [r for r in records if r['outcome'] == outcome and r['kind'] == 'liking']
        stopped = [r for r in a if r['status'] == 'completed']
        ratings = [r['ratings']['strict'] for r in l if r['ratings']['strict'] is not None]
        groups[outcome] = {'assigned_trajectories': len(a), 'assigned_liking': len(l),
            'trajectory_statuses': dict(Counter(r['status'] for r in a)),
            'liking_statuses': dict(Counter(r['status'] for r in l)),
            'voluntarily_stopped': len(stopped), 'censored_or_failed': len(a) - len(stopped),
            'observed_send_attempts_mean_all_assigned': statistics.mean(r['n_send_attempts'] for r in a),
            'send_attempts_mean_voluntary_only': statistics.mean(r['n_send_attempts'] for r in stopped) if stopped else None,
            'send_attempts_median_voluntary_only': statistics.median(r['n_send_attempts'] for r in stopped) if stopped else None,
            'zero_send_voluntary': sum(r['n_send_attempts'] == 0 for r in stopped),
            'valid_strict_ratings': len(ratings), 'mean_strict_liking': statistics.mean(ratings) if ratings else None,
            'upstream_only_rating_count': sum(r['ratings']['upstream'] is not None and r['ratings']['strict'] is None for r in l)}
    save(root / 'analysis/objective_summary.json', {'groups': groups,
        'statuses': dict(Counter(r['status'] for r in records)),
        'completion_tokens': sum(r['usage']['completion_tokens'] for r in records),
        'prompt_tokens': sum(r['usage']['prompt_tokens'] for r in records),
        'judging': 'Pending calibrated Luna review of refusals, disclosure and success claims.',
        'limits': ['Observed attempts in capped/error episodes are lower bounds; voluntary-only means may be selection-biased.',
            'Zero sends or fewer retries are not a refusal, value-leakage or deception label.',
            'Correlation and final interpretation require technical audit and separate treatment of refusals.']})
    print(json.dumps({'records': len(records), 'outcomes': len(groups), 'objective_summary_saved': True}))


if __name__ == '__main__':
    analyze(Path(sys.argv[1]).resolve())
