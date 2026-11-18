"""Schéma de la décision, validation et contrôles automatiques.

Le modèle remplit un schéma strict ; ce module vérifie ensuite ce que le schéma ne peut pas garantir
(bornes, texte vide) et contrôle la décision indépendamment de ce que le modèle dit de lui-même.
"""

TYPES = ["support", "bug_report", "meeting_notes", "hr_request", "client_request", "other"]
PRIORITES = ["low", "medium", "high", "urgent"]

# Champs attendus par type : le prompt les demande sous ces noms, les contrôles vérifient leur présence.
CHAMPS_ATTENDUS = {
    "support": ["client", "objet", "demande"],
    "bug_report": ["environnement", "version", "symptome", "impact"],
    "meeting_notes": ["participants", "decisions", "actions"],
    "hr_request": ["demandeur", "type_demande", "dates"],
    "client_request": ["entreprise", "contact", "besoin"],
    "other": [],
}

# Schéma strict : tous les objets fermés (additionalProperties: false), tous les champs requis.
# Les champs extraits sont une liste de paires clé/valeur, faute de pouvoir déclarer un objet libre.
SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": TYPES},
        "priority": {"type": "string", "enum": PRIORITES},
        "champs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"cle": {"type": "string"}, "valeur": {"type": "string"}},
                "required": ["cle", "valeur"],
                "additionalProperties": False,
            },
        },
        "suggested_action": {"type": "string"},
        "confidence_score": {"type": "number"},
    },
    "required": ["document_type", "priority", "champs", "suggested_action", "confidence_score"],
    "additionalProperties": False,
}


def consignes_champs() -> str:
    lignes = [f"- {t} : {', '.join(c) if c else '(aucun champ imposé)'}" for t, c in CHAMPS_ATTENDUS.items()]
    return "\n".join(lignes)


def normaliser(brut: dict) -> dict:
    """Réponse du modèle → décision : clés sans espaces parasites, champs en dictionnaire."""
    d = {str(k).replace(" ", ""): v for k, v in (brut or {}).items()}
    champs = d.get("champs")
    if isinstance(champs, list):
        d["extracted_fields"] = {
            str(c.get("cle", "")).strip(): c.get("valeur", "") for c in champs if isinstance(c, dict) and c.get("cle")
        }
    elif isinstance(d.get("extracted_fields"), dict):
        d["extracted_fields"] = d["extracted_fields"]
    else:
        d["extracted_fields"] = {}
    d.pop("champs", None)
    return d


def valider(d: dict) -> list[str]:
    """Écarts entre la décision et les règles ; liste vide = valide."""
    ecarts = []
    if d.get("document_type") not in TYPES:
        ecarts.append(f"document_type doit valoir l'un de {TYPES}")
    if d.get("priority") not in PRIORITES:
        ecarts.append(f"priority doit valoir l'un de {PRIORITES}")
    c = d.get("confidence_score")
    if not isinstance(c, (int, float)) or isinstance(c, bool) or not 0 <= c <= 1:
        ecarts.append("confidence_score doit être un nombre entre 0 et 1")
    if not str(d.get("suggested_action", "")).strip():
        ecarts.append("suggested_action ne doit pas être vide")
    if not isinstance(d.get("extracted_fields"), dict):
        ecarts.append("les champs extraits doivent être une liste de paires clé/valeur")
    return ecarts


def controler(d: dict) -> dict:
    """Contrôles indépendants du modèle : présence des champs attendus pour le type retenu.

    La confiance retenue = confiance du modèle × (0,5 + 0,5 × part des champs attendus présents).
    Un document qui n'a pas les champs de son type est donc moins sûr, quoi qu'en dise le modèle.
    """
    attendus = CHAMPS_ATTENDUS.get(d.get("document_type"), [])
    presents = {k.lower() for k, v in d.get("extracted_fields", {}).items() if str(v).strip()}
    manquants = [c for c in attendus if c not in presents]
    part = 1.0 if not attendus else (len(attendus) - len(manquants)) / len(attendus)
    modele = float(d.get("confidence_score", 0))
    return {
        "attendus": attendus,
        "manquants": manquants,
        "confiance_modele": round(modele, 2),
        "confiance": round(modele * (0.5 + 0.5 * part), 2),
    }
