# Current feedback system: source backup

This branch preserves the current system source on **October 30, 2026**, before the next update. Recovery tag: **`system-source-backup-2026-10-30`**. V1.zip, V2.zip and V3.zip are inherited unchanged from main.

The backup contains the executable `experiments/open_ended_sketch` source, UI assets, prompts, schemas, learner profiles and configuration, test scripts, project handoff and `draw2interaction` launch/integration notes. The 186 original files are copied byte-for-byte; [source_manifest.json](backup/source_manifest.json) records their sizes and SHA-256 hashes. [validation.json](backup/validation.json) records checks of the matching source with local resources.

The executable learner remains the two-Agent system with cached common K0 and three optional lists (`known`, `unknown`, `possibly_known`), projection `two-agent-cached-initial-knowledge-v6`. The five-profile binary-knowledge proposal remains a local design draft; it is not applied to this runtime. Read the [project handoff](experiments/open_ended_sketch/simulated_students/SIMULATED_LEARNERS.md) before updating the learner.

## Restore source before continuing development

```bash
git clone --branch system-source-backup-2026-10-30 https://github.com/Jiecao007/Multi-representation-feedback.git
cd Multi-representation-feedback
git switch -c my-next-update
python3 backup/verify_source.py
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r experiments/open_ended_sketch/requirements.txt
cp .env.example .env
```

Set your own API key locally in `.env`, then run:

```bash
python3 -B experiments/open_ended_sketch/app/server.py --port 8765
```

Open http://127.0.0.1:8765/. A fresh clone can accept new submissions; built-in examples need the original local `data/`, `inputs/` and `results/` resources. For rollback on the original machine, restore these source files over the existing project while retaining its local resources and `.env`. No dataset, historical evidence or generated session is overwritten by this source-only snapshot. Preserve a separate copy of later source edits before a rollback.

The optional browser learner needs Node.js, Google Chrome and Playwright; set `PLAYWRIGHT_MODULE` to the installed module on another machine. Submitting work or starting a live learner calls the configured API. The backup checks used local stubs and made no paid model calls.

## Excluded local materials

All additional `data/` and `outputs/` content, experiment `results/` and `inputs/`, generated `app/runs/`, recorded `tests/fixtures/`, credentials, installed dependencies, research documents, recordings and old system copies remain local. Historical links in the handoff and data-dependent regression scripts require those excluded resources. The source-only public snapshot does not include today's research drafts or additional student/example datasets.

Use the dated tag to identify the source saved before future updates. The existing main branch and its published V1–V3 archives remain unchanged.
