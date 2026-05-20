import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path("reports/governance.log")


def _next_id() -> int:
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0:
        return 1
    with LOG_PATH.open() as f:
        lines = [l for l in f.readlines() if l.strip()]
    if not lines:
        return 1
    last = json.loads(lines[-1])
    return last["id"] + 1


def log_decision(input_text: str, agent_result: dict) -> int:
    LOG_PATH.parent.mkdir(exist_ok=True)
    entry = {
        "id": _next_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_preview": input_text[:100],
        "decision": agent_result["result"],
        "model": agent_result["model"],
        "tokens_used": agent_result["tokens_used"],
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry["id"]


def print_summary() -> None:
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0:
        print("Aucune décision enregistrée.")
        return

    with LOG_PATH.open(encoding="utf-8") as f:
        entries = [json.loads(l) for l in f if l.strip()]

    if not entries:
        print("Aucune décision enregistrée.")
        return

    total = len(entries)
    avg_confidence = sum(e["decision"]["confidence_score"] for e in entries) / total

    type_counts: dict[str, int] = {}
    for e in entries:
        decision = {k.replace(" ", ""): v for k, v in e["decision"].items()}
        t = decision.get("document_type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"\nRapport de gouvernance — {total} décision(s)")
    print(f"Confiance moyenne  : {avg_confidence:.0%}")
    print("Répartition par type :")
    for doc_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        bar = "#" * count
        print(f"  {doc_type:<18} {bar} ({count})")
    print()
