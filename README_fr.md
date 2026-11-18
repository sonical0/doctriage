# DocTriage

Read this documentation in English: [README.md](README.md)

DocTriage est un agent en ligne de commande qui classe des documents, en extrait les champs utiles et propose une action, avec un score de confiance. **Tout tourne en local avec Ollama : aucune donnée ne quitte la machine.**

Il accepte tout texte libre (mails de support, tickets d'incident, comptes rendus, demandes RH, fiches client) et journalise chaque décision dans un fichier en ajout seul, sans y recopier le contenu des documents.

---

## Ce qu'il garantit

- **Sortie contrainte** : le modèle remplit un schéma JSON strict (sorties structurées d'Ollama). La décision est ensuite validée ; si elle enfreint une règle (confiance hors de 0–1, action vide…), elle est redemandée une fois avec la liste des écarts, puis refusée. Rien n'est inventé en repli.
- **Confiance contrôlée** : la confiance retenue ne dépend pas que de ce que le modèle dit de lui-même. Chaque type a ses champs attendus ; s'il en manque, la confiance baisse (confiance du modèle × (0,5 + 0,5 × part des champs présents)). Une **relecture** facultative par un second passage peut aussi la diviser par deux en cas de désaccord.
- **Journal sans données personnelles** : ni le texte, ni un extrait, ni les valeurs extraites (noms, adresses mail). Seuls restent l'empreinte SHA-256 du document, la décision, les confiances et les **noms** des champs.
- **Idempotent et rejouable** : un document déjà journalisé n'est ni réanalysé ni compté deux fois. Un lot qui échoue en partie se relance tel quel : seuls les documents en échec sont retraités.
- **Échecs explicites** : Ollama arrêté, modèle absent (avec la commande `ollama pull` à lancer), délai dépassé (une seule nouvelle tentative), réponse non conforme.

## Schéma

- **Types** : `support`, `bug_report`, `meeting_notes`, `hr_request`, `client_request`, `other`
- **Priorités** : `low`, `medium`, `high`, `urgent`
- **Champs attendus** :

| Type | Champs |
| --- | --- |
| support | client, objet, demande |
| bug_report | environnement, version, symptome, impact |
| meeting_notes | participants, decisions, actions |
| hr_request | demandeur, type_demande, dates |
| client_request | entreprise, contact, besoin |
| other | aucun imposé |

## Installation

```bash
git clone https://github.com/sonical0/doctriage.git
cd doctriage
pip install -r requirements.txt
ollama pull qwen3:8b          # modèle par défaut
```

Facultatif, dans un fichier `.env` (voir `.env.example`) : `OLLAMA_URL` (défaut `http://localhost:11434`), `OLLAMA_MODEL` (défaut `qwen3:8b`), `OLLAMA_TIMEOUT` en secondes (défaut 180).

## Utilisation

```bash
python main.py --input samples/ticket_bug.txt          # un fichier
python main.py --input "Mon abonnement n'est pas renouvelé depuis ce mois-ci."
python main.py --lot samples --relecture               # un dossier, avec relecture
python main.py --input samples/note_reunion.txt --model mistral-nemo --json
python main.py --summary                               # bilan du journal
```

`--force` réanalyse un document déjà journalisé ; `--relecture-modele` choisit un autre modèle pour la relecture.

## Exemple de sortie (réelle, qwen3:8b)

```
[DocTriage] Decision #5  [local / qwen3:8b]
--------------------------------------------------------
  Type              bug_report
  Priorite          high
  Confiance         95% (modele : 95%)
  Action suggeree   Rollback à la version 4.2.0 et investigation des logs pour identifier
                    la cause du TypeError dans le module de rendu des graphiques.
  Relecture         accord (Le type de document, la priorité et les champs extraits
                    correspondent fidèlement au texte du document.)

  Tokens : 1030 · 4.0 s
  Log enregistre : reports/governance.log (entree #5)
```

## Journal de gouvernance

`reports/governance.log`, une ligne JSON par décision :

```json
{"version": 2, "id": 5, "horodatage": "2026-11-18T21:05:57+00:00",
 "empreinte": "37af59c943b67e47240976c3de8dfc8534f7ddd4223f16f72fe00bf7aab5b8f1",
 "longueur": 1655, "reprise": false, "modele": "qwen3:8b",
 "type": "bug_report", "priorite": "high", "confiance_modele": 0.95, "confiance": 0.95,
 "champs": ["environnement", "impact", "symptome", "version"], "champs_manquants": [],
 "relecture": {"verdict": "accord", "modele": "qwen3:8b"}, "redemandes": 0,
 "tokens": 1852, "duree_ms": 4029}
```

Les échecs d'un lot vont dans `reports/echecs.jsonl` (source, empreinte, erreur), sans le texte. `--summary` lit aussi les entrées de l'ancien format.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Ollama est simulé : les tests ne font aucun appel réseau. Ils tournent à chaque push et à chaque pull request (GitHub Actions).

## Structure

```
doctriage/
  main.py           Interface en ligne de commande (fichier, texte, lot, bilan)
  agent.py          Appels Ollama, garde-fous, relecture
  schema.py         Schéma strict, validation, contrôles
  governance.py     Journal idempotent sans données personnelles
  samples/          5 documents d'exemple (FR)
  tests/            Tests sans réseau
```
