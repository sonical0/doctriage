# DocTriage

Lire cette documentation en français : [README_fr.md](README_fr.md)

DocTriage is a command-line agent that classifies documents, extracts the useful fields and suggests an action, with a confidence score. **Everything runs locally with Ollama: no data leaves the machine.**

It accepts any free-form text (support emails, incident tickets, meeting notes, HR requests, client files) and logs every decision to an append-only file, without copying the documents' content into it.

---

## What it guarantees

- **Constrained output**: the model fills a strict JSON schema (Ollama structured outputs). The decision is then validated; if it breaks a rule (confidence outside 0–1, empty action…), it is asked again once with the list of issues, then rejected. Nothing is made up as a fallback.
- **Checked confidence**: the retained confidence does not rely only on what the model says about itself. Each type has expected fields; missing ones lower the confidence (model confidence × (0.5 + 0.5 × share of fields present)). An optional **review** by a second pass halves it on disagreement.
- **Log without personal data**: no text, no excerpt, no extracted values (names, email addresses). Only the document's SHA-256 fingerprint, the decision, the confidences and the field **names** are kept.
- **Idempotent and replayable**: a document already logged is neither analysed again nor counted twice. A batch that partly fails is rerun as is: only the failed documents are processed again.
- **Explicit failures**: Ollama down, model missing (with the `ollama pull` command to run), timeout (a single retry), non-conforming answer.

## Schema

- **Types**: `support`, `bug_report`, `meeting_notes`, `hr_request`, `client_request`, `other`
- **Priorities**: `low`, `medium`, `high`, `urgent`
- **Expected fields** (French keys, as in the samples):

| Type | Fields |
| --- | --- |
| support | client, objet, demande |
| bug_report | environnement, version, symptome, impact |
| meeting_notes | participants, decisions, actions |
| hr_request | demandeur, type_demande, dates |
| client_request | entreprise, contact, besoin |
| other | none required |

## Installation

```bash
git clone https://github.com/sonical0/doctriage.git
cd doctriage
pip install -r requirements.txt
ollama pull qwen3:8b          # default model
```

Optional, in a `.env` file (see `.env.example`): `OLLAMA_URL` (default `http://localhost:11434`), `OLLAMA_MODEL` (default `qwen3:8b`), `OLLAMA_TIMEOUT` in seconds (default 180).

## Usage

```bash
python main.py --input samples/ticket_bug.txt          # one file
python main.py --input "My subscription has not renewed this month."
python main.py --lot samples --relecture               # a folder, with review
python main.py --input samples/note_reunion.txt --model mistral-nemo --json
python main.py --summary                               # log report
```

`--force` re-analyses a document already logged; `--relecture-modele` picks another model for the review.

## Governance log

`reports/governance.log`, one JSON line per decision (fingerprint, type, priority, confidences, field names, missing fields, review verdict, retries, tokens, duration). Batch failures go to `reports/echecs.jsonl` (source, fingerprint, error), without the text. `--summary` also reads entries in the previous format.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Ollama is simulated: tests make no network call. They run on every push and pull request (GitHub Actions).

## Structure

```
doctriage/
  main.py           Command-line interface (file, text, batch, report)
  agent.py          Ollama calls, guardrails, review
  schema.py         Strict schema, validation, checks
  governance.py     Idempotent log without personal data
  samples/          5 sample documents (FR)
  tests/            Network-free tests
```
