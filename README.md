# DocTriage

Accédez en Français: [README_fr.md](README_fr.md)

DocTriage is a command-line agent that classifies documents, extracts structured fields, and logs every decision with a confidence score and full traceability.

It accepts any free-form text (support emails, bug reports, meeting notes, HR requests, client files) and returns a structured JSON result, plus an append-only governance entry. No manual step is required between input and output.

Two inference backends are supported: **Claude API** (Anthropic) for cloud processing and **Ollama** for local inference. In local mode, no data leaves the machine.

---

## Table of contents (EN)

- [Value and use cases](#value-and-use-cases)
- [Architecture](#architecture)
- [Classification schema](#classification-schema)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Output examples](#output-examples)
- [Governance](#governance)
- [Project structure](#project-structure)
- [Extension ideas](#extension-ideas)

---

## Value and use cases

- **Reliable document triage**: 6 categories with type-specific field extraction.
- **Actionable output**: suggested action in French, priority level, confidence score.
- **Traceability**: every decision is logged as immutable JSON for auditability.
- **Local or cloud**: Ollama for data residency, Claude for performance.

---

## Architecture

```
Input (text or file)
         |
         v
+------------------+
|     main.py      |   CLI — parsing and formatted output
+--------+---------+
         |
         +--- --backend anthropic -------------------+
         |                                           |
         v                                           v
+--------------------+                 +--------------------+
|   Claude API       |                 |   Ollama (local)   |
|   forced tool use  |                 |   tool use or      |
|   prompt caching   |                 |   JSON fallback    |
|   retry on error   |                 |   no external call |
+--------+-----------+                 +--------+-----------+
         +-------------------+---------+
                             |
                             v
               classify_document tool result:
               {
                 document_type,
                 priority,
                 extracted_fields,
                 suggested_action,
                 confidence_score
               }
                             |
                             v
               +---------------------+
               |   governance.py     |   append JSON entry to
               |                     |   reports/governance.log
               +---------------------+
                             |
                             v
               Final JSON + governance entry
```

---

## Classification schema

- **Types**: `support`, `bug_report`, `meeting_notes`, `hr_request`, `client_request`, `other`
- **Priorities**: `low`, `medium`, `high`, `urgent`
- **Confidence**: score between 0.0 and 1.0
- **Extracted fields**: tailored to the document type

---

## Requirements

- Python 3.11+
- An Anthropic API key (cloud backend) or Ollama running locally

---

## Installation

```bash
git clone https://github.com/sonical0/doctriage.git
cd doctriage
pip install -r requirements.txt
cp .env.example .env
```

`.env` configuration:

```
ANTHROPIC_API_KEY=sk-ant-...

# Optional — only for Ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

Backends and defaults:

- **Anthropic** default model: `claude-haiku-4-5-20251001`
- **Ollama** default model: `llama3.2`, default URL: `http://localhost:11434`

---

## Usage

### Analyze a file

```bash
python main.py --input samples/email_support.txt
python main.py --input samples/ticket_bug.txt
```

### Analyze raw text

```bash
python main.py --input "Mon abonnement n'est pas renouvelle depuis ce mois-ci."
```

### Display governance summary

```bash
python main.py --summary
```

### Use the local backend (Ollama)

```bash
python main.py --input samples/email_support.txt --backend ollama
python main.py --input samples/ticket_bug.txt --backend ollama --ollama-model qwen3:14b
python main.py --input samples/note_reunion.txt --backend ollama --ollama-model dolphin-llama3:8b
```

Ollama models with native tool use (better structural accuracy): `llama3.1`, `llama3.2`, `qwen2.5`, `qwen3`, `mistral-nemo`.

Models without tool use (e.g. `dolphin-llama3`) fall back automatically to a constrained JSON prompt.

| Capability | Models (examples) | Behavior |
| --- | --- | --- |
| Native tool use | `llama3.1`, `llama3.2`, `qwen2.5`, `qwen3`, `mistral-nemo` | Tool use via `/v1/chat/completions` |
| No tool use | `dolphin-llama3` | Fallback to constrained JSON prompt |

---

## Output examples

### Support email — billing complaint

```
[DocTriage] Decision #4  [backend: ollama / dolphin-llama3:8b]
--------------------------------------------------------
  Type              support
  Priority          urgent
  Confidence        90%
  Suggested action  Verifier les transactions du compte bancaire de la cliente
                    pour identifier la cause du double prelevement. Proceder
                    au remboursement de la somme prelevee en trop (89,90 EUR)
                    dans les plus brefs delais et confirmer par email.

  Extracted fields:
    from_email: marie.dupont@gmail.com
    to_email: support@monservice.fr
    subject: Probleme de facturation urgent - double prelevement
    customer_id: 2024-FR-00847

  Tokens : 862
  Log recorded : reports/governance.log (entry #4)
```

### Bug report — production incident

```
[DocTriage] Decision #6  [backend: ollama / qwen3:14b]
--------------------------------------------------------
  Type              bug_report
  Priority          urgent
  Confidence        98%
  Suggested action  Prioriser la correction du bug PDF export (urgence critique)
                    et accelerer le rollback vers la version 4.2.0

  Extracted fields:
    reported_by: Thomas Renard (t.renard@acme.fr)
    environment: Production
    version: 4.2.1
    error_description: Export PDF genere des fichiers corrompus avec graphiques dynamiques
    logs: [ERROR] pdf-renderer - Chart rendering failed: TypeError: ...
    context: Deploiement version 4.2.1 hier soir (patch auth), probleme apparu a 08h45
    impact: Bloquant pour l equipe finance (15 utilisateurs, deadline 12h00)
    actions_taken: Redemarrage service pdf-renderer, test en recette, rollback 4.2.0 en cours

  Tokens : 1511
  Log recorded : reports/governance.log (entry #6)
```

### Governance summary

```
Governance report — 6 decision(s)
Average confidence  : 95%
Distribution by type :
  bug_report         ### (3)
  support            ### (3)
```

---

## Governance

Every decision is appended as a JSON line to `reports/governance.log`. The file is human-readable and machine-parseable: one JSON object per line, append-only, never modified after writing.

```json
{
  "id": 6,
  "timestamp": "2026-05-19T22:35:10.123456+02:00",
  "input_preview": "TICKET INCIDENT - Plateforme analytique interne\nRapporte par : Thomas Renard...",
  "decision": {
    "document_type": "bug_report",
    "priority": "urgent",
    "extracted_fields": {
      "environment": "Production",
      "version": "4.2.1",
      "impact": "Bloquant pour l equipe finance (15 utilisateurs, deadline 12h00)"
    },
    "suggested_action": "Prioriser la correction du bug PDF export et accelerer le rollback vers la version 4.2.0",
    "confidence_score": 0.98
  },
  "model": "qwen3:14b",
  "tokens_used": 1511
}
```

Each entry records an ID, a UTC timestamp, a 100-character input preview, the structured result, the model name, and token usage. Run `python main.py --summary` for aggregated statistics.

---

## Project structure

```
doctriage/
  main.py           Command-line interface
  agent.py          Inference logic (Anthropic + Ollama), tool use, JSON fallback
  governance.py     Decision logging and stats
  samples/          Five French sample documents
  reports/          Governance logs (excluded from VCS)
  requirements.txt
  .env.example
```

---

## Extension ideas

1. **Web interface** — expose the classification logic via a FastAPI endpoint with file upload
2. **Multi-agent routing** — route decisions to the right team inbox
3. **IMAP connector** — poll a mailbox, classify messages, and apply labels
