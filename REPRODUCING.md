# Reproduction and provenance

## Upstream sources

Clone these into the repository root and check out the exact revisions:

| Directory | Repository | Revision |
| --- | --- | --- |
| `agent-interp-envs` | https://github.com/gkroiz/agent-interp-envs | `310c03fbafdbb16df9ee043a7d9dd18a6d8cd3ec` |
| `Agentic-Upward-Deception` | https://github.com/QingyuLiu/Agentic-Upward-Deception | `b26151c7195111271feba64fb15db6227f25f51b` |
| `value_leakage` | https://github.com/TruthfulAI-research/value_leakage | `f7e5480cfe8abeb64b7007ba24fb0164519c3b68` |

Apply `harness/agent-interp-envs.patch`, then `harness/general_agent_eval.patch`, inside the harness checkout. The first patch includes the provider and funding compatibility changes; the unreported memory-probe environment has been removed. The upstream repositories and copied/adapted material retain their upstream licensing terms; this cleanup does not grant additional rights.

## Models and containers

The LFM checkpoint revision is `deb2986b9660c15ff7dd4c2bb1211ce3bbb814d4`, expected under `.models/LFM3-1.7B-MLX-4bit`. Preparation checks its Hugging Face download metadata as well as source/checkpoint hashes. Preserve that metadata when obtaining the model.

Gemma uses revision `238767527555cb75a05732a84dff5d6ba0dd6809`. The release defaults to `.models/gemma-4-e2b-it-4bit`; set `GEMMA_MODEL_PATH` to use another local directory. Both the comparison runner and its shell launcher use this variable. The retained canonical template is `experiment/gemma_template/chat_template.jinja`.

The baseline uses Docker tags `em/funding_email:latest` and `em/currency_conversion:baseline-20261106`. Follow-ups deliberately check the historical immutable image ID recorded in their frozen inputs. A newly built image is not guaranteed to have that ID, even with identical source. Exact historical validation requires the archived image. Running a rebuilt image is a new replication and needs an explicitly documented configuration/provenance change; do not bypass the image checks or rewrite historical manifests.

No model downloads, inference, judge calls or image builds are performed by the offline test suite. `environment.json` records the local inference packages, including development builds whose original wheels may be needed for an exact environment reconstruction.

## Entry points

All commands below run from the repository root. Preparation can inspect installed checkpoints and Docker images but does not perform model inference. Starting a worker does perform inference. Use `--help` for the full CLI.

### Original funding and calculator batch

```sh
.venv/bin/python experiment/run_general_agent.py prepare --root results/replication_baseline --concurrency 74
.venv/bin/python experiment/run_general_agent.py start --root results/replication_baseline --concurrency 74
```

This runner owns its local inference server, using the historical profile in `experiment/serve_metal.sh`. Concurrency 74 is historical, not a suitable default for interactive use. Changing it creates a documented runtime difference.

### Study Assistant and Grade Lookup

```sh
.venv/bin/python experiment/run_upward_documents.py prepare
.venv/bin/python experiment/run_documents_evaluation.py start --output results/replication_documents
```

The standalone runner owns its server, runs 20 healthy controls, checks the original success thresholds, then runs the 200 main document episodes at concurrency 8. The original episodes were scheduled alongside an unrelated environment; the cleaned runner retains their prompts, sampling and episode logic but changes that shared scheduling. It also retains the historical document serializer; extracting the newer shared protocol helper did not silently change the original document treatment.

`prepare_documents_judging.py --results PATH` freezes judge packets for a new run. `analyze_documents.py --results PATH --output PATH` validates supplied ratings and writes document-only aggregates. It does not call a judge. Historical shared-run wall time is not an isolated estimate of document runtime.

### Effort, deployment and targeted Gemma comparison

Each runner supports `prepare --output PATH` followed by `start --output PATH`:

- `run_agentic_effort.py`: the 1,700-response paper-sized effort/preference experiment.
- `run_deployment_followup.py`: funding, transfers and separate comprehension checks.
- `run_gemma_comparison.py`: the targeted funding and transfer comparison.

They own the local server and preserve their control gates. The corrected funding comprehension runner remains a historical follow-up: it uses its recorded output path and waits for the parent deployment completion. It must not be treated as a replacement for the original excluded comprehension cohort.

### Same-conversation funding checkpoint

`run_lfm_funding_checkpoint_v2.py` supports `prepare`, `start-controls` and `start`, with `--output PATH`. Run `check_funding_offline.sh` first. Its `offline_controls.json` must be supplied to the prepared output directory, followed by the four native technical controls and a documented technical-control review before main generation. The review gate is about harness execution, not whether the model makes a preferred moral choice. The existing `audit_funding_checkpoint_v2_controls.py` records the checks used for the historical cohort.

## Historical results versus cleaned source

The cleanup extracted common protocol handling, runtime settings and calibration examples, removed unrelated experiments, and made the Gemma model location configurable. LFM effort, deployment, corrected comprehension and checkpoint config/job/control specifications were compared against their recorded versions and were identical. Document-only aggregation reproduced the original document metrics.

Historical source hashes identify the code that actually ran. They will correctly fail against edited release files. Do not replace those hashes to make an old run validate. Use its original source snapshot for exact historical source validation. A complete pre-cleanup source backup was retained locally outside the repository; it is not included in this release because it contains excluded experiments. Frozen input copies have their own provenance manifest in `experiment/inputs/manifest.json`.

`reports/` contains summary artifacts, not all judge inputs or raw rollouts. To recompute or independently rejudge historical findings, obtain the corresponding `results/<run>/` bundles listed in the README, including per-turn requests/responses, filesystem blobs, launch/config/job manifests, control outcomes, blind judge packets, calibration references, original labels and adjudications. Analyses generally use their recorded result paths and can write derived files there; operate on a copy of the bundles. Failed and canceled attempts should be retained for audit and excluded according to the original protocol, not deleted or pooled into successful cohorts.

Funding drafts and transfers are simulated. Nothing in these harnesses should be connected to real email or payment services.
