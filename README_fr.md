# DocTriage

Read this documentation in English: [README.md](README.md)

DocTriage est un agent en ligne de commande pour classer des documents, extraire des champs structurés, et journaliser chaque décision avec un score de confiance et une traçabilité complète.

Il accepte tout texte libre (emails support, tickets d'incident, comptes-rendus, demandes RH, fiches client) et renvoie un JSON structuré, accompagné d'une entrée de gouvernance append-only. Aucun traitement manuel n'est requis entre l'entrée et la sortie.

Deux backends sont disponibles : **Claude API** (Anthropic) pour le cloud, et **Ollama** pour l'inférence locale. En mode local, aucune donnée ne sort de la machine.

---

## Sommaire (FR)

- [Valeur et cas d'usage](#valeur-et-cas-dusage)
- [Architecture](#architecture)
- [Schema de classification](#schema-de-classification)
- [Exigences](#exigences)
- [Installation](#installation)
- [Utilisation](#utilisation)
- [Exemples de sortie](#exemples-de-sortie)
- [Gouvernance](#gouvernance)
- [Structure du projet](#structure-du-projet)
- [Idees d'extensions](#idees-dextensions)

---

## Valeur et cas d'usage

-- **Triage documentaire fiable** : classification en 6 types et extraction de champs métier adaptés.
-- **Actionnable** : action suggérée en français, niveau de priorité, score de confiance.
-- **Traçabilité** : chaque décision est journalisée en JSON, immuable et auditable.
-- **Local ou cloud** : Ollama pour la souveraineté des données, Claude pour la performance.

---

## Architecture

```
Input (texte ou fichier)
         |
         v
+------------------+
|     main.py      |   CLI — parsing, sortie formatee
+--------+---------+
         |
         +--- --backend anthropic -------------------+
         |                                           |
         v                                           v
+--------------------+                 +--------------------+
|   Claude API       |                 |   Ollama (local)   |
|   tool use forcé   |                 |   tool use ou      |
|   prompt caching   |                 |   fallback JSON    |
|   retry on error   |                 |   aucun appel externe |
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
               JSON final + entree de gouvernance
```

---

## Schéma de classification

- **Types** : `support`, `bug_report`, `meeting_notes`, `hr_request`, `client_request`, `other`
- **Priorités** : `low`, `medium`, `high`, `urgent`
- **Confiance** : score de 0.0 à 1.0
- **Champs extraits** : adaptés au type de document

---

## Exigences

- Python 3.11+
- Une clé API Anthropic (backend cloud) ou Ollama en local

---

## Installation

```bash
git clone https://github.com/sonical0/doctriage.git
cd doctriage
pip install -r requirements.txt
cp .env.example .env
```

Configuration `.env` :

```
ANTHROPIC_API_KEY=sk-ant-...

# Optionnel — uniquement pour Ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

Backends et valeurs par défaut :

- **Anthropic** : modèle par défaut `claude-haiku-4-5-20251001`
- **Ollama** : modèle par défaut `llama3.2` et URL `http://localhost:11434`

---

## Utilisation

### Analyser un fichier

```bash
python main.py --input samples/email_support.txt
python main.py --input samples/ticket_bug.txt
```

### Analyser du texte brut

```bash
python main.py --input "Mon abonnement n'est pas renouvelé depuis ce mois-ci."
```

### Afficher le résumé de gouvernance

```bash
python main.py --summary
```

### Utiliser le backend local (Ollama)

```bash
python main.py --input samples/email_support.txt --backend ollama
python main.py --input samples/ticket_bug.txt --backend ollama --ollama-model qwen3:14b
python main.py --input samples/note_reunion.txt --backend ollama --ollama-model dolphin-llama3:8b
```

Modèles Ollama avec tool use natif (meilleure précision structurelle) : `llama3.1`, `llama3.2`, `qwen2.5`, `qwen3`, `mistral-nemo`.

Modèles sans tool use natif (ex. : `dolphin-llama3`) : fallback automatique vers un prompt JSON contraint.

| Capacité | Modèles (exemples) | Comportement |
| --- | --- | --- |
| Tool use natif | `llama3.1`, `llama3.2`, `qwen2.5`, `qwen3`, `mistral-nemo` | Tool use via `/v1/chat/completions` |
| Sans tool use | `dolphin-llama3` | Fallback vers prompt JSON contraint |

---

## Exemples de sortie

### Email support — plainte de facturation

```
[DocTriage] Decision #4  [backend: ollama / dolphin-llama3:8b]
--------------------------------------------------------
  Type              support
  Priorité          urgent
  Confiance         90%
  Action suggérée   Vérifier les transactions du compte bancaire de la cliente
                    pour identifier la cause du double prélèvement. Procéder
                    au remboursement de la somme prélevée en trop (89,90 EUR)
                    dans les plus brefs délais et confirmer par email.

  Champs extraits :
    from_email: marie.dupont@gmail.com
    to_email: support@monservice.fr
    subject: Problème de facturation urgent - double prélèvement
    customer_id: 2024-FR-00847

  Tokens : 862
  Log enregistré : reports/governance.log (entrée #4)
```

### Bug report — incident en production

```
[DocTriage] Decision #6  [backend: ollama / qwen3:14b]
--------------------------------------------------------
  Type              bug_report
  Priorité          urgent
  Confiance         98%
  Action suggérée   Prioriser la correction du bug d'export PDF (urgence critique)
                    et accélérer le rollback vers la version 4.2.0

  Champs extraits :
    reported_by: Thomas Renard (t.renard@acme.fr)
    environment: Production
    version: 4.2.1
    error_description: Export PDF généré des fichiers corrompus avec graphiques dynamiques
    logs: [ERROR] pdf-renderer - Chart rendering failed: TypeError: ...
    context: Déploiement version 4.2.1 hier soir (patch auth), problème apparu à 08h45
    impact: Bloquant pour l'équipe finance (15 utilisateurs, deadline 12h00)
    actions_taken: Redémarrage service pdf-renderer, test en recette, rollback 4.2.0 en cours

  Tokens : 1511
  Log enregistré : reports/governance.log (entrée #6)
```

### Resume de gouvernance

```
Rapport de gouvernance — 6 décision(s)
Confiance moyenne  : 95%
Répartition par type :
  bug_report         ### (3)
  support            ### (3)
```

---

## Gouvernance

Chaque décision est ajoutée dans `reports/governance.log` sous forme d'une ligne JSON. Le fichier est lisible et machine-parseable : un objet JSON par ligne, append-only, jamais modifié.

```json
{
  "id": 6,
  "timestamp": "2026-05-19T22:35:10.123456+02:00",
  "input_preview": "TICKET INCIDENT - Plateforme analytique interne\nRapporté par : Thomas Renard...",
  "decision": {
    "document_type": "bug_report",
    "priority": "urgent",
    "extracted_fields": {
      "environment": "Production",
      "version": "4.2.1",
      "impact": "Bloquant pour l'équipe finance (15 utilisateurs, deadline 12h00)"
    },
    "suggested_action": "Prioriser la correction du bug d'export PDF et accélérer le rollback vers la version 4.2.0",
    "confidence_score": 0.98
  },
  "model": "qwen3:14b",
  "tokens_used": 1511
}
```

Chaque entrée enregistre un identifiant, un timestamp en UTC, un aperçu des 100 premiers caractères, le résultat structuré, le modèle, et le nombre de tokens. La commande `python main.py --summary` produit un résumé agrégé.

---

## Structure du projet

```
doctriage/
  main.py           Interface CLI
  agent.py          Inference (Anthropic + Ollama), tool use, fallback JSON
  governance.py     Journalisation et statistiques
  samples/          5 documents d'exemple (FR)
  reports/          Logs de gouvernance (hors VCS)
  requirements.txt
  .env.example
```

---

## Idées d'extensions

1. **Web interface** — exposer la classification via FastAPI avec upload de fichier
2. **Multi-agent routing** — router les décisions vers la bonne équipe
3. **IMAP connector** — classifier les emails entrants et appliquer des labels
