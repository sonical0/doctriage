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


def _print_result(result: dict, decision_id: int, backend: str) -> None:
    r = result["result"]
    backend_label = f"backend: {backend} / {result['model']}"

    print(_color(f"\n[DocTriage] Decision #{decision_id}  [{backend_label}]", Fore.CYAN))
    print(_color("-" * 56, Fore.CYAN))

    fields = [
        ("Type", r["document_type"]),
        ("Priorite", r["priority"]),
        ("Confiance", f"{r['confidence_score']:.0%}"),
        ("Action suggeree", r["suggested_action"]),
    ]
    for label, value in fields:
        print(_color(f"  {label:<18}", Fore.YELLOW) + str(value))

    print(_color("\n  Champs extraits :", Fore.YELLOW))
    for k, v in r["extracted_fields"].items():
        print(f"    {_color(k, Fore.WHITE)}: {v}")

    print(_color("\n  Sortie JSON complete :", Fore.YELLOW))
    print(json.dumps(r, ensure_ascii=False, indent=2))

    print(_color(f"\n  Tokens : {result['tokens_used']}", Fore.CYAN))
    print(_color(f"  Log enregistre : reports/governance.log (entree #{decision_id})", Fore.GREEN))
    print()


def run_input(text: str, backend: str, ollama_model: str, ollama_url: str) -> None:
    print(_color(f"Analyse en cours... [backend: {backend}]", Fore.CYAN))
    try:
        result = agent.classify(text, backend=backend, ollama_model=ollama_model, ollama_url=ollama_url)
    except Exception as exc:
        print(_color(f"Erreur : {exc}", Fore.RED), file=sys.stderr)
        sys.exit(1)

    decision_id = governance.log_decision(text, result)
    _print_result(result, decision_id, backend)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DocTriage — agent de triage documentaire",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Exemples :
  python main.py --input samples/email_support.txt
  python main.py --input "Mon abonnement n'est pas renouvelé..."
  python main.py --input samples/email_support.txt --backend ollama
  python main.py --input samples/ticket_bug.txt --backend ollama --ollama-model qwen2.5
  python main.py --summary""",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", metavar="TEXTE_OU_FICHIER", help="Texte a analyser ou chemin vers un fichier .txt")
    group.add_argument("--summary", action="store_true", help="Afficher les statistiques de gouvernance")

    parser.add_argument(
        "--backend",
        choices=["anthropic", "ollama"],
        default="anthropic",
        help="Backend LLM : 'anthropic' (defaut, API externe) ou 'ollama' (local, donnees non transmises)",
    )
    parser.add_argument("--ollama-model", default=None, metavar="MODEL", help="Modele Ollama (defaut : llama3.2)")
    parser.add_argument("--ollama-url", default=None, metavar="URL", help="URL Ollama (defaut : http://localhost:11434)")

    args = parser.parse_args()

    if args.summary:
        governance.print_summary()
        return

    path = Path(args.input)
    if path.exists() and path.is_file():
        text = path.read_text(encoding="utf-8")
    else:
        text = args.input

    if not text.strip():
        print("Erreur : le texte fourni est vide.", file=sys.stderr)
        sys.exit(1)

    run_input(text, args.backend, args.ollama_model, args.ollama_url)


if __name__ == "__main__":
    main()
