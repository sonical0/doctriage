"""Inférence locale avec Ollama : aucune donnée ne quitte la machine.

Garde-fous (repris de ce qui a tenu en production sur d'autres projets) :
- sortie contrainte par le schéma JSON de schema.py (sorties structurées d'Ollama) ;
- délai par appel, une seule nouvelle tentative sur erreur serveur ou délai dépassé ;
- décision validée ; si elle enfreint une règle, une seule redemande avec la liste des écarts ;
- aucun repli silencieux : un échec lève une erreur explicite, rien n'est inventé ;
- modèle absent détecté avant l'appel, avec la commande pour l'installer.
"""

import json
import os
import time

import requests

import schema

try:  # variables OLLAMA_* depuis un fichier local facultatif
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DEFAULT_MODEL = "qwen3:8b"
DEFAULT_URL = "http://localhost:11434"
DELAI_S = float(os.environ.get("OLLAMA_TIMEOUT", "180"))
REDEMANDES_MAX = 1

SYSTEM_PROMPT = f"""Tu es un agent de triage documentaire. Tu lis un document en français ou en anglais et tu
remplis le schéma demandé, sans rien inventer.

Types :
- support : réclamation client, facturation, abonnement
- bug_report : erreur technique, panne, incident
- meeting_notes : compte rendu, décisions, actions d'une réunion
- hr_request : congés, demande RH
- client_request : prospect, opportunité commerciale, demande d'un client
- other : tout le reste

Champs à extraire, sous ces noms exacts quand l'information figure dans le document (ajoute d'autres
champs utiles si besoin, et omets un champ absent plutôt que de l'inventer) :
{schema.consignes_champs()}

suggested_action : une action précise en français. confidence_score : ta confiance entre 0 et 1."""

PROMPT_RELECTURE = """Tu relis la décision d'un autre agent de triage. Compare-la au document : le type et la
priorité sont-ils justes, les champs extraits fidèles au texte (rien d'inventé) ? Réponds « accord » ou
« desaccord », avec un motif court en français."""

SCHEMA_RELECTURE = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["accord", "desaccord"]}, "motif": {"type": "string"}},
    "required": ["verdict", "motif"],
    "additionalProperties": False,
}


class ErreurOllama(RuntimeError):
    pass


def _url(base: str, chemin: str) -> str:
    return f"{base.rstrip('/')}{chemin}"


def verifier_modele(model: str, base_url: str, session=requests) -> None:
    """Échoue tôt, avec la commande à lancer, si Ollama ne répond pas ou n'a pas le modèle."""
    try:
        r = session.get(_url(base_url, "/api/tags"), timeout=10)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise ErreurOllama(f"Ollama injoignable sur {base_url} ({exc}). Lancer « ollama serve ».") from exc
    noms = {m.get("name", "") for m in r.json().get("models", [])}
    if model not in noms and f"{model}:latest" not in noms:
        raise ErreurOllama(f"Modèle « {model} » absent d'Ollama. L'installer : ollama pull {model}")


def _appel(messages: list, fmt: dict, model: str, base_url: str, session=requests, attendre=time.sleep) -> dict:
    """Un appel /api/chat ; une seule nouvelle tentative sur erreur 5xx ou délai dépassé."""
    payload = {
        "model": model,
        "messages": messages,
        "format": fmt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    for tentative in range(2):
        debut = time.monotonic()
        try:
            r = session.post(_url(base_url, "/api/chat"), json=payload, timeout=DELAI_S)
        except requests.Timeout as exc:
            if tentative == 0:
                continue
            raise ErreurOllama(f"Délai dépassé ({DELAI_S:.0f} s) deux fois de suite") from exc
        except requests.RequestException as exc:
            raise ErreurOllama(f"Ollama injoignable : {exc}") from exc
        if r.status_code >= 500 and tentative == 0:
            attendre(2)
            continue
        if r.status_code >= 400:
            raise ErreurOllama(f"Ollama a refusé l'appel (HTTP {r.status_code}) : {r.text[:200]}")
        data = r.json()
        try:
            contenu = json.loads(data["message"]["content"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise ErreurOllama(f"Réponse non conforme au schéma : {str(data)[:200]}") from exc
        return {
            "contenu": contenu,
            "tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            "duree_ms": int((time.monotonic() - debut) * 1000),
        }
    raise ErreurOllama("Ollama en erreur deux fois de suite")


def classify(text: str, model: str | None = None, base_url: str | None = None, session=requests) -> dict:
    model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    base_url = base_url or os.environ.get("OLLAMA_URL", DEFAULT_URL)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}]
    tokens = duree = 0
    for essai in range(REDEMANDES_MAX + 1):
        rep = _appel(messages, schema.SCHEMA, model, base_url, session)
        tokens += rep["tokens"]
        duree += rep["duree_ms"]
        decision = schema.normaliser(rep["contenu"])
        ecarts = schema.valider(decision)
        if not ecarts:
            return {
                "result": decision,
                "controles": schema.controler(decision),
                "model": model,
                "tokens_used": tokens,
                "duree_ms": duree,
                "redemandes": essai,
            }
        messages += [
            {"role": "assistant", "content": json.dumps(rep["contenu"], ensure_ascii=False)},
            {"role": "user", "content": "Ta réponse enfreint ces règles, corrige-la :\n- " + "\n- ".join(ecarts)},
        ]
    raise ErreurOllama("Décision invalide après redemande : " + " ; ".join(ecarts))


def relire(text: str, decision: dict, model: str | None = None, base_url: str | None = None, session=requests) -> dict:
    """Relecture par un second modèle (local) : accord ou désaccord, avec motif."""
    model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    base_url = base_url or os.environ.get("OLLAMA_URL", DEFAULT_URL)
    messages = [
        {"role": "system", "content": PROMPT_RELECTURE},
        {"role": "user", "content": f"Document :\n{text}\n\nDécision :\n{json.dumps(decision, ensure_ascii=False)}"},
    ]
    rep = _appel(messages, SCHEMA_RELECTURE, model, base_url, session)
    v = rep["contenu"]
    if v.get("verdict") not in ("accord", "desaccord"):
        raise ErreurOllama(f"Relecture non conforme : {v}")
    return {"verdict": v["verdict"], "motif": str(v.get("motif", "")), "modele": model, "tokens": rep["tokens"]}


def appliquer_relecture(controles: dict, relecture: dict | None) -> dict:
    """Un désaccord de la relecture divise la confiance retenue par deux."""
    c = dict(controles)
    if relecture and relecture["verdict"] == "desaccord":
        c["confiance"] = round(c["confiance"] / 2, 2)
    return c
