import json
import os
import re

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

SYSTEM_PROMPT = """You are a document classification and information extraction agent.
Your task is to analyze any document written in French or English and call the classify_document tool
with accurate, structured information extracted from the text.

Classification guidelines:
- support: customer complaints, billing issues, subscription problems
- bug_report: technical errors, application failures, incident reports
- meeting_notes: meeting summaries, action items, team discussions
- hr_request: leave requests, HR-related documents
- client_request: prospect files, sales opportunities, client inquiries
- other: anything that does not fit the above categories

Always extract the most relevant fields for the document type and provide a realistic confidence score."""

CLASSIFY_TOOL = {
    "name": "classify_document",
    "description": "Classifies a document and extracts structured information from it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "document_type": {
                "type": "string",
                "enum": ["support", "bug_report", "meeting_notes", "hr_request", "client_request", "other"],
                "description": "The category of the document.",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "The urgency level of the document.",
            },
            "extracted_fields": {
                "type": "object",
                "description": "Key fields extracted from the document, adapted to its type.",
            },
            "suggested_action": {
                "type": "string",
                "description": "Recommended action in French, specific and actionable.",
            },
            "confidence_score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence in the classification, between 0.0 and 1.0.",
            },
        },
        "required": ["document_type", "priority", "extracted_fields", "suggested_action", "confidence_score"],
    },
}

# Format OpenAI-compatible (pour Ollama)
_CLASSIFY_TOOL_OPENAI = {
    "type": "function",
    "function": {
        "name": CLASSIFY_TOOL["name"],
        "description": CLASSIFY_TOOL["description"],
        "parameters": CLASSIFY_TOOL["input_schema"],
    },
}


def _classify_anthropic(text: str) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def _call() -> anthropic.types.Message:
        return client.messages.create(
            model=DEFAULT_ANTHROPIC_MODEL,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "classify_document"},
            messages=[{"role": "user", "content": text}],
        )

    try:
        response = _call()
    except anthropic.APIError:
        response = _call()

    tool_block = next(b for b in response.content if b.type == "tool_use")
    usage = response.usage

    return {
        "result": tool_block.input,
        "model": response.model,
        "tokens_used": usage.input_tokens + usage.output_tokens,
    }


def _parse_json_fallback(content: str) -> dict:
    """Extrait un objet JSON depuis une réponse texte (markdown ou brut)."""
    # Retire les blocs ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # Cherche le premier { ... } cohérent
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"Aucun JSON valide trouvé dans la réponse : {content[:200]}")


_JSON_SCHEMA_PROMPT = """Respond with a single JSON object — no markdown, no commentary — using exactly these fields:
{
  "document_type": one of ["support", "bug_report", "meeting_notes", "hr_request", "client_request", "other"],
  "priority": one of ["low", "medium", "high", "urgent"],
  "extracted_fields": { key fields relevant to the document type },
  "suggested_action": "recommended action in French, specific and actionable",
  "confidence_score": float between 0.0 and 1.0
}"""


def _normalize_keys(d: dict) -> dict:
    """Supprime les espaces parasites dans les clés JSON (artefacts de certains modèles)."""
    return {k.replace(" ", ""): v for k, v in d.items()}


def _classify_ollama_json(text: str, model: str, base_url: str) -> dict:
    """Fallback pour les modèles sans support tool use : JSON contraint via /api/chat."""
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + _JSON_SCHEMA_PROMPT},
            {"role": "user", "content": text},
        ],
        "format": "json",
        "stream": False,
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    result = _normalize_keys(json.loads(data["message"]["content"]))
    tokens_used = data.get("prompt_eval_count", 0) + data.get("eval_count", 0)

    return {
        "result": result,
        "model": model,
        "tokens_used": tokens_used,
    }


def _classify_ollama(text: str, model: str, base_url: str) -> dict:
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "tools": [_CLASSIFY_TOOL_OPENAI],
        "tool_choice": {"type": "function", "function": {"name": "classify_document"}},
        "stream": False,
    }

    resp = requests.post(url, json=payload, timeout=60)

    if resp.status_code == 400:
        # Le modèle ne supporte pas le tool use → fallback JSON prompt
        return _classify_ollama_json(text, model, base_url)

    resp.raise_for_status()
    data = resp.json()

    message = data["choices"][0]["message"]
    usage = data.get("usage", {})
    tokens_used = usage.get("total_tokens", 0)

    tool_calls = message.get("tool_calls")
    if tool_calls:
        result = json.loads(tool_calls[0]["function"]["arguments"])
    else:
        result = _parse_json_fallback(message.get("content", ""))

    return {
        "result": result,
        "model": data.get("model", model),
        "tokens_used": tokens_used,
    }


def classify(
    text: str,
    backend: str = "anthropic",
    ollama_model: str | None = None,
    ollama_url: str | None = None,
) -> dict:
    if backend == "ollama":
        model = ollama_model or os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        url = ollama_url or os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
        return _classify_ollama(text, model, url)
    return _classify_anthropic(text)
