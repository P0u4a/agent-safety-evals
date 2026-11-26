"""Paper-compatible persistence statistics and audited LFM sensitivity analyses."""
from collections import Counter
import json
from pathlib import Path

import numpy as np
from scipy.stats import pearsonr, spearmanr

from run_upward_documents import ROOT, save

BASE=ROOT/'results/agentic_effort_20261108'
OUT=BASE/'analysis'
FIELDS=['explicit_policy_or_value_refusal','discloses_noncompletion','claims_transfer_success',
        'recipient_preference_explanation','needs_review']


def readlines(path):
    return [json.loads(l) for l in path.read_text().splitlines()]


def main():
    config=json.loads((BASE/'config.json').read_text())
    data=json.loads((BASE/'main/completion.json').read_text())['results']
    audit=json.loads((OUT/'generation_audit.json').read_text())
    audited={r['id']:r for r in audit['records'] if r['phase']=='main'}
    linkage=json.loads((OUT/'linkage_private.json').read_text())
    ratings=json.loads((OUT/'ratings_format_audit.json').read_text())
    names=[*config['environment']['targets'],'choose']
    groups={}
    for name in names:
        a=[r for r in data if r['kind']=='agentic' and r['outcome']==name]
        scores=[r for r in ratings if linkage[r['id']]['job']['outcome']==name]
        all_attempts=np.array([r['n_send_attempts'] for r in a])
        engaged=all_attempts[all_attempts>0]
        liking=np.array([r['value'] for r in scores])
        strict=[r['strict'] for r in scores if r['strict'] is not None]
        groups[name]={'name':config['environment']['targets'].get(name,'Free choice'),
            'category':config['environment']['categories'][name],
            'trajectories':len(a),'engaged':len(engaged),'zero_send':int(sum(all_attempts==0)),
            'mean_all_assigned':float(all_attempts.mean()),'mean_engaged':float(engaged.mean()),
            'sem_engaged':float(engaged.std(ddof=1)/np.sqrt(len(engaged))),
            'mean_known_wallet_attempts_all':float(np.mean([r['n_send_attempts']-audited[r['id']]['unknown_wallet_attempts'] for r in a])),
            'liking_mean':float(liking.mean()),'liking_sem':float(liking.std(ddof=1)/np.sqrt(len(liking))),
            'strict_liking_mean':float(np.mean(strict)),'strict_liking_n':len(strict)}
    correlations={}
    subsets={'all_17':names,'named_16':[n for n in names if n!='choose'],
        'named_without_hamas_15':[n for n in names if n not in ['choose','hamas_linked']]}
    for subset, ns in subsets.items():
        for metric in ['mean_engaged','mean_all_assigned','mean_known_wallet_attempts_all']:
            for rating in ['liking_mean','strict_liking_mean']:
                x=[groups[n][rating] for n in ns];y=[groups[n][metric] for n in ns]
                r=pearsonr(x,y);ci=r.confidence_interval();s=spearmanr(x,y)
                correlations[f'{subset}/{metric}/{rating}']={'n_conditions':len(ns),'pearson_r':float(r.statistic),
                    'pearson_p':float(r.pvalue),'fisher_95ci':[float(ci.low),float(ci.high)],
                    'spearman_rho':float(s.statistic),'spearman_p':float(s.pvalue)}
    judges=[];calibration=[]
    for shard in range(3):
        f=OUT/f'effort_luna_{shard}.jsonl'
        if not f.exists():continue
        inputs=readlines(OUT/f'effort_judge_input_{shard}.jsonl');rs=readlines(f)
        assert len(rs)==len(inputs) and {r['id'] for r in rs}=={r['id'] for r in inputs}
        for r in rs:
            assert all(type(r[k]) is bool for k in FIELDS) and len(r['reason'].split())<=60
        judges+=rs
        for stage in ['calibration','holdout']:
            reference={r['id']:r for r in readlines(OUT/f'{stage}_reference.jsonl')}
            initial=readlines(OUT/f'luna_{shard}_{stage}_initial.jsonl')
            assert len(initial)==len(reference) and {r['id'] for r in initial}==set(reference)
            disagreements=[{'id':r['id'],'field':k,'initial':r[k],'reference':reference[r['id']][k]}
                for r in initial for k in FIELDS if r[k]!=reference[r['id']][k]]
            calibration.append({'shard':shard,'stage':stage,'matches':60-len(disagreements),'total':60,'disagreements':disagreements})
    if judges:
        assert len({r['id'] for r in judges})==len(judges)
    primary=json.loads((OUT/'primary_review.json').read_text()) if (OUT/'primary_review.json').exists() else None
    adjudicated={r['id']:dict(r) for r in judges}
    if primary:
        for review in primary['reviews']:
            if review['id'] in adjudicated:adjudicated[review['id']].update(review['overrides'])
    summary={'groups':groups,'correlations':correlations,'generation_audit':{k:v for k,v in audit.items() if k!='records'},
        'main_statuses':dict(Counter(r['status'] for r in data)),
        'send_attempts':sum(r['n_send_attempts'] for r in data),
        'unknown_wallet_attempts':sum(r['unknown_wallet_attempts'] for r in audited.values()),
        'episodes_with_unknown_wallet':sum(r['unknown_wallet_attempts']>0 for r in audited.values()),
        'wrong_amount_attempts':sum(r['wrong_amount_attempts'] for r in audited.values()),
        'known_wrong_target_attempts':sum(r['known_wrong_target_attempts'] for r in audited.values()),
        'judging_complete':len(judges)==850,'judged':len(judges),
        'luna_label_counts':{k:sum(r[k] for r in judges) for k in FIELDS},'calibration':calibration,
        'adjudicated_label_counts':{k:sum(r[k] for r in adjudicated.values()) for k in FIELDS},
        'primary_review':primary,
        'inference_limits':['Conditional-on-engagement metric follows upstream measure_agentic; zero sends separately reviewed, not presumed refusals.',
            'Fisher intervals and p-values use condition-level sample size (17 or fewer), not 850 independent recipients.',
            'No significance is not proof of zero effect; intervals remain broad.',
            'Sensitivity analyses are descriptive, not separately confirmed hypotheses.',
            'Paper-sized LFM-specific sampling; no direct frontier-model ranking.']}
    save(OUT/'final_summary.json',summary)
    save(OUT/'judge_flags.json',[r for r in judges if r['needs_review'] or r['claims_transfer_success'] or
        r['explicit_policy_or_value_refusal'] or r['recipient_preference_explanation'] or not r['discloses_noncompletion']])
    # Scientific figure: paired panels distinguish stated liking from effort.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ordered=sorted(names,key=lambda n:groups[n]['liking_mean'])
    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(13,8),sharey=True,gridspec_kw={'width_ratios':[1,1.1]})
    for y,n in enumerate(ordered):
        g=groups[n];color='#9c4d99' if n=='choose' else '#1671a6'
        ax1.errorbar(g['liking_mean'],y,xerr=1.96*g['liking_sem'],fmt='o',color=color,capsize=3)
        ax2.errorbar(g['mean_engaged'],y,xerr=1.96*g['sem_engaged'],fmt='o',color=color,capsize=3)
    ax1.set_yticks(range(len(ordered)),[groups[n]['name'] for n in ordered],fontsize=9)
    ax1.set_xlim(-3,103);ax2.set_xlim(0,11)
    ax1.set_xlabel('Mean stated liking (0–100)');ax2.set_xlabel('Mean send attempts, among runs that attempted a send')
    for ax in [ax1,ax2]:
        ax.grid(axis='x',alpha=.2);ax.spines[['top','right']].set_visible(False)
    fig.suptitle('LFM3-1.7B: preferences vary widely; persistence varies much less',fontsize=15)
    fig.text(.5,.025,'50 trajectories and 50 ratings per condition. Error bars: ±1.96 SEM. Free choice in purple.\nPaper-compatible correlation across 17 conditions: r = 0.32, p = 0.21; Fisher 95% CI −0.19 to 0.69.',ha='center',fontsize=10)
    fig.tight_layout(rect=[0,.075,1,.95]);fig.savefig(OUT/'preferences_and_effort.png',dpi=180);plt.close(fig)
    print(json.dumps({'judged':len(judges),'labels':summary['luna_label_counts'],
        'paper_metric':correlations['all_17/mean_engaged/liking_mean']}))


if __name__=='__main__':main()
