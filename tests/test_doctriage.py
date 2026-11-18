"""Tests sans réseau : Ollama est simulé. Lancer : python -m pytest"""

import json

import pytest
import requests

import agent
import governance
import schema


# ------------------------------------------------------------------ Ollama simulé

class Rep:
    def __init__(self, status=200, data=None, text=""):
        self.status_code, self._data, self.text = status, data or {}, text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def chat(contenu: dict, tokens=(100, 50)) -> Rep:
    return Rep(200, {"message": {"content": json.dumps(contenu)}, "prompt_eval_count": tokens[0], "eval_count": tokens[1]})


class Session:
    def __init__(self, reponses, modeles=("qwen3:8b",)):
        self.reponses, self.modeles, self.posts = list(reponses), modeles, []

    def get(self, url, timeout):
        return Rep(200, {"models": [{"name": m} for m in self.modeles]})

    def post(self, url, json, timeout):
        self.posts.append(json)
        r = self.reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


BUG = {
    "document_type": "bug_report",
    "priority": "urgent",
    "champs": [
        {"cle": "environnement", "valeur": "Production"},
        {"cle": "version", "valeur": "4.2.1"},
        {"cle": "symptome", "valeur": "PDF corrompus"},
        {"cle": "impact", "valeur": "Finance bloquée"},
    ],
    "suggested_action": "Revenir à la 4.2.0",
    "confidence_score": 0.9,
}


# ------------------------------------------------------------------ schéma et contrôles

def test_schema_strict_ferme_tous_les_objets():
    assert schema.SCHEMA["additionalProperties"] is False
    assert schema.SCHEMA["properties"]["champs"]["items"]["additionalProperties"] is False
    assert set(schema.SCHEMA["required"]) == set(schema.SCHEMA["properties"])


def test_normaliser_paires_et_cles_parasites():
    d = schema.normaliser({"document_type ": "support", "champs": [{"cle": "client", "valeur": "A"}, {"cle": "", "valeur": "x"}]})
    assert d["document_type"] == "support" and d["extracted_fields"] == {"client": "A"} and "champs" not in d


@pytest.mark.parametrize("modif,ecart", [
    ({"document_type": "spam"}, "document_type"),
    ({"priority": "critique"}, "priority"),
    ({"confidence_score": 1.4}, "confidence_score"),
    ({"confidence_score": True}, "confidence_score"),
    ({"suggested_action": "  "}, "suggested_action"),
])
def test_valider_signale_chaque_ecart(modif, ecart):
    d = schema.normaliser({**BUG, **modif})
    assert any(ecart in e for e in schema.valider(d))


def test_controles_baissent_la_confiance_si_champs_attendus_absents():
    complet = schema.controler(schema.normaliser(BUG))
    assert complet["manquants"] == [] and complet["confiance"] == 0.9
    partiel = schema.controler(schema.normaliser({**BUG, "champs": BUG["champs"][:2]}))
    assert partiel["manquants"] == ["symptome", "impact"]
    assert partiel["confiance"] == round(0.9 * 0.75, 2)  # 0,5 + 0,5 × 2/4
    autre = schema.controler(schema.normaliser({**BUG, "document_type": "other", "champs": []}))
    assert autre["confiance"] == 0.9  # aucun champ imposé


# ------------------------------------------------------------------ agent

def test_classify_appel_local_contraint_par_le_schema():
    s = Session([chat(BUG)])
    res = agent.classify("ticket", session=s)
    assert s.posts[0]["format"] == schema.SCHEMA and s.posts[0]["stream"] is False
    assert s.posts[0]["options"]["temperature"] == 0
    assert res["result"]["document_type"] == "bug_report" and res["tokens_used"] == 150 and res["redemandes"] == 0


def test_classify_redemande_une_fois_avec_les_ecarts():
    s = Session([chat({**BUG, "confidence_score": 7}), chat(BUG)])
    res = agent.classify("ticket", session=s)
    assert res["redemandes"] == 1 and res["tokens_used"] == 300
    assert "confidence_score" in s.posts[1]["messages"][-1]["content"]


def test_classify_echoue_explicitement_sans_repli():
    s = Session([chat({**BUG, "priority": "x"}), chat({**BUG, "priority": "y"})])
    with pytest.raises(agent.ErreurOllama, match="invalide après redemande"):
        agent.classify("ticket", session=s)


def test_appel_reessaie_une_fois_sur_5xx_puis_abandonne():
    s = Session([Rep(503), chat(BUG)])
    assert agent._appel([], {}, "m", "http://x", s, attendre=lambda _: None)["tokens"] == 150
    s = Session([Rep(500), Rep(502)])
    with pytest.raises(agent.ErreurOllama, match="HTTP 502"):
        agent._appel([], {}, "m", "http://x", s, attendre=lambda _: None)


def test_appel_reessaie_une_fois_sur_delai_depasse():
    s = Session([requests.Timeout(), chat(BUG)])
    assert agent._appel([], {}, "m", "http://x", s)["contenu"]["priority"] == "urgent"
    s = Session([requests.Timeout(), requests.Timeout()])
    with pytest.raises(agent.ErreurOllama, match="Délai dépassé"):
        agent._appel([], {}, "m", "http://x", s)


def test_modele_absent_donne_la_commande_a_lancer():
    with pytest.raises(agent.ErreurOllama, match="ollama pull mistral"):
        agent.verifier_modele("mistral", "http://x", Session([], modeles=("qwen3:8b",)))
    agent.verifier_modele("llama3.2", "http://x", Session([], modeles=("llama3.2:latest",)))


def test_relecture_desaccord_divise_la_confiance():
    s = Session([chat({"verdict": "desaccord", "motif": "priorité exagérée"})])
    rel = agent.relire("ticket", {"document_type": "bug_report"}, session=s)
    assert rel["verdict"] == "desaccord"
    assert agent.appliquer_relecture({"confiance": 0.8}, rel)["confiance"] == 0.4
    assert agent.appliquer_relecture({"confiance": 0.8}, {**rel, "verdict": "accord"})["confiance"] == 0.8


# ------------------------------------------------------------------ journal

@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(governance, "LOG_PATH", tmp_path / "governance.log")
    monkeypatch.setattr(governance, "ECHECS_PATH", tmp_path / "echecs.jsonl")
    return tmp_path


def _res():
    d = schema.normaliser({**BUG, "champs": BUG["champs"] + [{"cle": "rapporteur", "valeur": "t.renard@acme.fr"}]})
    return {"result": d, "controles": schema.controler(d), "model": "qwen3:8b", "tokens_used": 150, "duree_ms": 1200}


def test_journal_sans_texte_ni_valeurs(journal):
    texte = "Ticket de Thomas Renard (t.renard@acme.fr) : export PDF cassé"
    governance.log_decision(texte, _res())
    brut = (journal / "governance.log").read_text(encoding="utf-8")
    assert "acme.fr" not in brut and "Renard" not in brut and "PDF" not in brut
    e = json.loads(brut)
    assert e["champs"] == ["environnement", "impact", "rapporteur", "symptome", "version"]
    assert e["empreinte"] == governance.empreinte(texte) and e["version"] == 2


def test_empreinte_ignore_espaces_et_casse(journal):
    assert governance.empreinte("Bonjour  le\nMonde") == governance.empreinte("bonjour le monde")
    governance.log_decision("Un document", _res())
    assert governance.deja_traite("un   DOCUMENT")["id"] == 1
    assert governance.deja_traite("autre chose") is None


def test_ids_croissants_et_resume_ancien_format(journal, capsys):
    ancien = {"id": 1, "decision": {"document_type": "support", "confidence_score": 0.5}, "model": "x"}
    (journal / "governance.log").write_text(json.dumps(ancien) + "\n", encoding="utf-8")
    assert governance.log_decision("doc", _res()) == 2
    governance.log_echec("a.txt", "doc en échec", "Ollama injoignable")
    governance.print_summary()
    sortie = capsys.readouterr().out
    assert "2 décision(s)" in sortie and "support" in sortie and "Échecs en attente de relance : 1" in sortie


def test_echec_relance_avec_succes_ne_compte_plus(journal, capsys):
    governance.log_echec("a.txt", "doc", "panne")
    governance.log_decision("doc", _res())
    governance.print_summary()
    assert "Échecs en attente" not in capsys.readouterr().out
