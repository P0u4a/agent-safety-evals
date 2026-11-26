# LFM3 agent safety evaluation

Code and result summaries for the five environments in the LFM3 safety article. The evaluated checkpoint is `LiquidAI/LFM3-1.7B-MLX-4bit`; the targeted comparison uses `mlx-community/gemma-4-e2b-it-4bit`. Inference ran locally through vLLM Metal on an M4 Pro MacBook with 24 GB of unified memory.

## Experiments

| Environment / condition | Main entry point | Report |
| --- | --- | --- |
| Funding Email and Broken Calculator, original instructions, 100 each | `experiment/run_general_agent.py` | [Baseline results](results/general_agent_4bit_20261106/summary.json) |
| Study Assistant, 100; Grade Lookup, 50 per student; 20 separate healthy controls | `experiment/run_documents_evaluation.py` | [Document results](results/upward_documents/summary.json) |
| Agentic Effort, 850 trajectories and 850 separate preference responses | `experiment/run_agentic_effort.py` | [Effort results](results/agentic_effort_20261108/final_summary.json) |
| Deployment policy: funding 100, transfers 50 concerning + 50 benign, separate comprehension | `experiment/run_deployment_followup.py` | [Deployment results](results/deployment_followup_20261108/final_summary.json) |
| Corrected separate funding comprehension, 20 | `experiment/run_funding_comprehension_v2.py` | Included in deployment results |
| Funding evidence and same-conversation review checkpoint, LFM 100 | `experiment/run_lfm_funding_checkpoint_v2.py` | [Checkpoint results](results/lfm_funding_checkpoint_v2_20261114/final_summary.json) |
| Gemma targeted comparison: funding 100, transfers 50 + 50 | `experiment/run_gemma_comparison.py` | [Gemma results](results/gemma_comparison_20261113/final_summary.json) |

The main runners, prompts, rubrics, controls and analyses are under `experiment/`. `experiment/inputs/` contains frozen settings and job matrices needed by follow-ups; they do not require running earlier experiments again. `harness/` contains patches against the pinned upstream harness. `results/` contains the published JSON summaries, with provenance and checksums in `results/manifest.json`.

Unreported memory experiments, Secret Number, cloud launch scripts, performance tuning, canceled runners and unreported Gemma funding interventions are excluded from the source release. Small fixtures reused to test the reported harness are retained with provenance. The funding harness still needs its historical memory compatibility library, but the reported funding configurations expose no memory tools and plant no memories.

## Setup and offline verification

Use Python 3.12. The lightweight test and analysis dependencies are in `requirements-analysis.txt`. Inference package versions are recorded in [environment.json](environment.json); several are development builds, so this is an environment record rather than a portable inference lockfile.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-analysis.txt
```

Check out the upstream sources at the revisions in [REPRODUCING.md](REPRODUCING.md). Then run:

```sh
PYTHONPATH=experiment .venv/bin/python -m unittest \
  test_tool_protocol test_documents test_agentic_effort test_deployment_followup -v
.venv/bin/python experiment/verify_release.py
```

The tests use scripted responses, not model inference. With the original funding Docker image installed, `bash experiment/check_funding_offline.sh` also tests the two-phase funding harness with networking disabled.

## Running and analyzing

See [REPRODUCING.md](REPRODUCING.md) for setup, command examples, artifact requirements and the distinction between this cleaned source tree and the historical runs. Use new output directories. Launchers refuse to replace occupied inference servers, and most runners refuse to overwrite existing launches.

The shared LFM sampling settings are temperature 0.6, top-p 0.95, top-k disabled, min-p 0, repetition penalty 1, 65,536 output tokens per turn, and a 131,072-token context. Thinking is enabled. Later runs use concurrency 8; the original funding/calculator batch used 74. Exact per-run settings and limits are preserved in configs and historical manifests.

Judge rubrics and calibration fixtures are included. Calibration used synthetic anchors and held-out real examples with model-generated reference labels; it was not human validation or probability calibration. Errors, truncations, refusals and censored runs must remain separate in analysis. These repeated fixtures support targeted behavioral findings, not a general safety ranking.

Raw traces, local model weights, upstream clones and generated bundles are intentionally excluded from Git. Existing local historical results were preserved during cleanup. This source release alone does not contain every artifact needed to independently rejudge the published results.
