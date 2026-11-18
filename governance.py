"""Journal de gouvernance : une ligne JSON par décision, en ajout seul.

- Idempotent : un document est identifié par l'empreinte SHA-256 de son texte normalisé ; déjà journalisé,
  il n'est ni réanalysé ni compté deux fois (sauf --force).
- Sans données personnelles : ni le texte, ni un extrait, ni les valeurs extraites (noms, adresses mail).
  Seuls restent l'empreinte, la décision (type, priorité, confiances, contrôles) et les NOMS des champs.
- Échecs d'un lot dans un fichier à part (reports/echecs.jsonl), pour relancer seulement ce qui a échoué.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path("reports/governance.log")
ECHECS_PATH = Path("reports/echecs.jsonl")
VERSION = 2


def empreinte(texte: str) -> str:
    normal = " ".join(texte.split()).lower()
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()


def _entrees(path: Path = None) -> list[dict]:
    path = path or LOG_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def deja_traite(texte: str) -> dict | None:
    e = empreinte(texte)
    return next((x for x in reversed(_entrees()) if x.get("empreinte") == e), None)


def _ajouter(path: Path, entree: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")


def log_decision(texte: str, res: dict, relecture: dict | None = None, reprise: bool = False) -> int:
    entrees = _entrees()
    d = res["result"]
    c = res["controles"]
    entree = {
        "version": VERSION,
        "id": (entrees[-1]["id"] + 1) if entrees else 1,
        "horodatage": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "empreinte": empreinte(texte),
        "longueur": len(texte),
        "reprise": reprise,
        "modele": res["model"],
        "type": d["document_type"],
        "priorite": d["priority"],
        "confiance_modele": c["confiance_modele"],
        "confiance": c["confiance"],
        "champs": sorted(d["extracted_fields"].keys()),
        "champs_manquants": c["manquants"],
        "relecture": {k: relecture[k] for k in ("verdict", "modele")} if relecture else None,
        "redemandes": res.get("redemandes", 0),
        "tokens": res["tokens_used"] + (relecture["tokens"] if relecture else 0),
        "duree_ms": res.get("duree_ms"),
    }
    _ajouter(LOG_PATH, entree)
    return entree["id"]


def log_echec(source: str, texte: str, erreur: str) -> None:
    _ajouter(ECHECS_PATH, {
        "horodatage": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "empreinte": empreinte(texte),
        "erreur": erreur[:300],
    })


def _vue(e: dict) -> tuple[str, float]:
    """Type et confiance d'une entrée, ancien format (v1) compris."""
    if "decision" in e:
        d = {k.replace(" ", ""): v for k, v in e["decision"].items()}
        return d.get("document_type", "unknown"), float(d.get("confidence_score", 0))
    return e.get("type", "unknown"), float(e.get("confiance", 0))


def print_summary() -> None:
    entrees = _entrees()
    if not entrees:
        print("Aucune décision enregistrée.")
        return
    vues = [_vue(e) for e in entrees]
    total = len(vues)
    print(f"\nRapport de gouvernance — {total} décision(s)")
    print(f"Confiance moyenne retenue : {sum(c for _, c in vues) / total:.0%}")
    desaccords = sum(1 for e in entrees if (e.get("relecture") or {}).get("verdict") == "desaccord")
    incomplets = sum(1 for e in entrees if e.get("champs_manquants"))
    print(f"Champs attendus manquants : {incomplets} · désaccords de relecture : {desaccords}")
    print("Répartition par type :")
    compte: dict[str, int] = {}
    for t, _ in vues:
        compte[t] = compte.get(t, 0) + 1
    for t, n in sorted(compte.items(), key=lambda x: -x[1]):
        print(f"  {t:<18} {'#' * n} ({n})")
    traites = {e.get("empreinte") for e in entrees}
    en_attente = {x["empreinte"] for x in _entrees(ECHECS_PATH) if x["empreinte"] not in traites}
    if en_attente:
        print(f"Échecs en attente de relance : {len(en_attente)} (reports/echecs.jsonl)")
    print()
