"""Rate the body-backed news digest and write provenance-rich AI ratings."""
import json
import logging
import os
import sys
from datetime import datetime, timezone
import news_digest

log = logging.getLogger("news_claude")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
MODEL = os.environ.get("NEWS_AI_MODEL", "claude-haiku-4-5")
MAX_TOKENS = int(os.environ.get("NEWS_AI_MAX_TOKENS", "4096"))
TIMEOUT = float(os.environ.get("NEWS_AI_TIMEOUT", "120"))
OUT_PATH = os.path.join(os.path.dirname(__file__), "news_ai_ratings.json")
CAUSALITY = {"causal", "correlated", "noise"}
HORIZONS = {"single_session", "multi_session"}
VALID_RATINGS = {"highly_positive", "positive", "neutral", "negative",
                 "highly_negative"}
SYSTEM = (
    "You classify verified Pakistan-equities news for real-money decision support. "
    "Use only the supplied title and publisher text. Never infer missing facts. "
    "Causal means a stated mechanism to cash flow or valuation; correlated means "
    "related but not causal; noise means no defensible mechanism. Confidence is a "
    "number from 0 to 1. Prefer neutral/noise when evidence is ambiguous."
)
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "rating": {"type": "string", "enum": sorted(VALID_RATINGS)},
        "reason": {"type": "string", "maxLength": 200},
        "causality": {"type": "string", "enum": sorted(CAUSALITY)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "horizon": {"type": "string", "enum": sorted(HORIZONS)},
    },
    "required": ["rating", "reason", "causality", "confidence", "horizon"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": "object", "additionalProperties": VERDICT_SCHEMA},
        "sector": {"type": "object", "additionalProperties": VERDICT_SCHEMA},
    },
    "required": ["company", "sector"],
    "additionalProperties": False,
}

def _build_prompt(digest):
    lines = ["Rate every company and sector key below. Return each exact key under "
             "the matching company or sector object. depth=headline means only an "
             "RSS lede was available."]
    for group in ("company", "sector"):
        lines.append(f"\n{group.upper()}:")
        for key, items in digest.get(group, {}).items():
            lines.append(f"\n{key}:")
            for item in items:
                lines.append(f"- [{item.get('source')}; {item.get('published')}; "
                             f"depth={item.get('depth')}] {item.get('title')}\n"
                             f"  TEXT: {item.get('text') or '[no publisher text]'}")
    return "\n".join(lines)

def _call_claude(prompt, client):
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined to classify this batch")
    text = "".join(b.text for b in resp.content if b.type == "text")
    log.info("in=%d out=%d tokens", resp.usage.input_tokens, resp.usage.output_tokens)
    return json.loads(text)

def _sanitize_group(raw, evidence):
    out = {}
    for key, verdict in (raw or {}).items():
        if key not in evidence or not isinstance(verdict, dict):
            continue
        rating = str(verdict.get("rating", "")).lower().replace("-", "_")
        causality, confidence = verdict.get("causality"), verdict.get("confidence")
        horizon = verdict.get("horizon")
        if (rating not in VALID_RATINGS or causality not in CAUSALITY
                or horizon not in HORIZONS or isinstance(confidence, bool)
                or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
            continue
        items = evidence[key]
        sources = [i.get("url") for i in items if i.get("url")]
        published = [i.get("published") for i in items if i.get("published")]
        out[key] = {
            "rating": rating, "reason": str(verdict.get("reason") or "")[:200],
            "causality": causality, "confidence": float(confidence), "horizon": horizon,
            "text_depth": "full" if any(i.get("depth") == "full" for i in items) else "headline",
            "sources": list(dict.fromkeys(sources)),
            "source_published": list(dict.fromkeys(published)),
        }
    return out

def main():
    try:
        import anthropic
    except ImportError:
        log.error("anthropic package is not installed")
        return 1
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set")
        return 1
    digest = news_digest.build()
    if not digest.get("company") and not digest.get("sector"):
        log.error("digest contains no rateable company or sector evidence")
        return 1
    client = anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT)
    try:
        raw = _call_claude(_build_prompt(digest), client)
    except anthropic.AuthenticationError:
        log.error("ANTHROPIC_API_KEY rejected (401)")
        return 1
    except Exception as exc:
        log.error("Claude call failed: %s", exc)
        return 1
    ratings = _sanitize_group(raw.get("company"), digest["company"])
    sectors = _sanitize_group(raw.get("sector"), digest["sector"])
    if not ratings and not sectors:
        log.error("model returned no valid ratings")
        return 1
    payload = {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_fetched_at": digest.get("fetched_at"),
        "provider": "anthropic", "model": MODEL,
        "count": len(ratings), "sector_count": len(sectors),
        "ratings": ratings, "sectors": sectors,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    log.info("Wrote %d company and %d sector ratings", len(ratings), len(sectors))
    return 0

if __name__ == "__main__":
    sys.exit(main())
