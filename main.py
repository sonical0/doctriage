import argparse
import json
import sys
from pathlib import Path

# Force UTF-8 sur la sortie console (Windows cp1252 par défaut)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init()
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False

import agent
import governance


def _color(text: str, color: str) -> str:
    if not HAS_COLOR:
        return text
    return f"{color}{text}{Style.RESET_ALL}"


def _print_result(res: dict, decision_id: int, relecture: dict | None, json_complet: bool) -> None:
    r = res["result"]
    c = res["controles"]
    print(_color(f"\n[DocTriage] Decision #{decision_id}  [local / {res['model']}]", Fore.CYAN))
    print(_color("-" * 56, Fore.CYAN))
    lignes = [
        ("Type", r["document_type"]),
        ("Priorite", r["priority"]),
        ("Confiance", f"{c['confiance']:.0%} (modele : {c['confiance_modele']:.0%})"),
        ("Action suggeree", r["suggested_action"]),
    ]
    for label, value in lignes:
        print(_color(f"  {label:<18}", Fore.YELLOW) + str(value))
    if c["manquants"]:
        print(_color(f"  {'Controles':<18}", Fore.YELLOW) + "champs attendus absents : " + ", ".join(c["manquants"]))
    if relecture:
        couleur = Fore.GREEN if relecture["verdict"] == "accord" else Fore.RED
        print(_color(f"  {'Relecture':<18}", Fore.YELLOW) + _color(relecture["verdict"], couleur) + f" ({relecture['motif']})")

    print(_color("\n  Champs extraits :", Fore.YELLOW))
    for k, v in r["extracted_fields"].items():
        print(f"    {_color(k, Fore.WHITE)}: {v}")

    if json_complet:
        print(_color("\n  Sortie JSON complete :", Fore.YELLOW))
        print(json.dumps({**r, "controles": c, "relecture": relecture}, ensure_ascii=False, indent=2))

    print(_color(f"\n  Tokens : {res['tokens_used']} · {res['duree_ms'] / 1000:.1f} s", Fore.CYAN))
    print(_color(f"  Log enregistre : reports/governance.log (entree #{decision_id})", Fore.GREEN))
    print()


def traiter(texte: str, args, source: str = "") -> bool:
    """Analyse un texte ; renvoie False en cas d'échec (journalisé à part, sans le texte)."""
    precedente = governance.deja_traite(texte)
    if precedente and not args.force:
        print(_color(f"Deja traite : decision #{precedente['id']} ({precedente['type']}){' — ' + source if source else ''}", Fore.CYAN))
        return True
    print(_color(f"Analyse en cours... [local : {args.model or agent.DEFAULT_MODEL}]{' — ' + source if source else ''}", Fore.CYAN))
    try:
        res = agent.classify(texte, model=args.model, base_url=args.ollama_url)
        relecture = None
        if args.relecture:
            relecture = agent.relire(texte, res["result"], model=args.relecture_modele or args.model, base_url=args.ollama_url)
            res["controles"] = agent.appliquer_relecture(res["controles"], relecture)
    except agent.ErreurOllama as exc:
        print(_color(f"Erreur : {exc}", Fore.RED), file=sys.stderr)
        governance.log_echec(source or "texte", texte, str(exc))
        return False
    decision_id = governance.log_decision(texte, res, relecture, reprise=bool(precedente))
    _print_result(res, decision_id, relecture, args.json)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DocTriage — agent de triage documentaire, 100 % local (Ollama)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Exemples :
  python main.py --input samples/email_support.txt
  python main.py --input "Mon abonnement n'est pas renouvelé..."
  python main.py --lot samples --relecture
  python main.py --summary""",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", metavar="TEXTE_OU_FICHIER", help="Texte a analyser ou chemin vers un fichier .txt")
    group.add_argument("--lot", metavar="DOSSIER", help="Analyser tous les .txt d'un dossier (deja traites ignores)")
    group.add_argument("--summary", action="store_true", help="Afficher les statistiques de gouvernance")
    parser.add_argument("--model", default=None, metavar="MODELE", help=f"Modele Ollama (defaut : {agent.DEFAULT_MODEL})")
    parser.add_argument("--ollama-url", default=None, metavar="URL", help=f"URL Ollama (defaut : {agent.DEFAULT_URL})")
    parser.add_argument("--relecture", action="store_true", help="Faire relire chaque decision par un second passage")
    parser.add_argument("--relecture-modele", default=None, metavar="MODELE", help="Modele de la relecture (defaut : le meme)")
    parser.add_argument("--force", action="store_true", help="Reanalyser un document deja journalise")
    parser.add_argument("--json", action="store_true", help="Afficher aussi la sortie JSON complete")
    args = parser.parse_args()

    if args.summary:
        governance.print_summary()
        return

    try:
        agent.verifier_modele(args.model or agent.DEFAULT_MODEL, args.ollama_url or agent.DEFAULT_URL)
        if args.relecture and args.relecture_modele:
            agent.verifier_modele(args.relecture_modele, args.ollama_url or agent.DEFAULT_URL)
    except agent.ErreurOllama as exc:
        print(_color(f"Erreur : {exc}", Fore.RED), file=sys.stderr)
        sys.exit(1)

    if args.lot:
        fichiers = sorted(Path(args.lot).glob("*.txt"))
        if not fichiers:
            print(f"Aucun fichier .txt dans {args.lot}", file=sys.stderr)
            sys.exit(1)
        echecs = sum(not traiter(f.read_text(encoding="utf-8"), args, f.name) for f in fichiers)
        print(f"Lot termine : {len(fichiers) - echecs}/{len(fichiers)} sans erreur" + (f", {echecs} echec(s) dans reports/echecs.jsonl : relancer la meme commande" if echecs else ""))
        sys.exit(1 if echecs else 0)

    path = Path(args.input)
    try:
        est_fichier = path.is_file()
    except (OSError, ValueError):  # texte brut qui n'est pas un chemin valide (Windows)
        est_fichier = False
    texte = path.read_text(encoding="utf-8") if est_fichier else args.input
    if not texte.strip():
        print("Erreur : le texte fourni est vide.", file=sys.stderr)
        sys.exit(1)
    sys.exit(0 if traiter(texte, args, path.name if est_fichier else "") else 1)


if __name__ == "__main__":
    main()
