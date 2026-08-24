"""news_claude.py — Rate each symbol's last-24h headlines with Claude Haiku 4.5
into one of: highly_positive / positive / neutral / negative / highly_negative.
Writes news_ai_ratings.json.

Replaces news_glm.py as the primary rater. The GLM path still works and is the
fallback when ANTHROPIC_API_KEY is unset, so a missing key degrades to the old
behaviour rather than leaving the dashboard with no second opinion at all.

Zero score weight — the rating is a SECOND OPINION shown next to the engine's
Buy/Avoid so the user can eyeball whether the model's read agrees. Never fed
into the score, exactly like GLM.

Token-frugal by construction:
  - ONE batched request for every symbol that has fresh headlines, not one per
    symbol. 50 symbols would otherwise be 50 round trips.
  - Haiku 4.5 ($1/$5 per 1M) — the cheapest current model, and news
    classification is the kind of shallow task it is built for.
  - Headlines only, never article bodies; capped per symbol.
  - Structured output via a strict JSON schema, so the reply is a small object
    with no prose preamble to pay for.
  - No extended thinking: Haiku 4.5 predates adaptive thinking, and
    output_config.effort errors on it. Neither is wanted for classification.

Reuses news_glm's headline collection and sanitiser so the credibility filter,
the anchor gate and the rating vocabulary cannot drift between the two raters.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import anthropic

import config
import news_glm

log = logging.getLogger("news_claude")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

MODEL = os.environ.get("NEWS_AI_MODEL", "claude-haiku-4-5")
# Classification only: the reply is one short object per symbol. 50 symbols at
# ~30 tokens each still fits well inside this, and a low cap is the cheapest
# guard against a runaway response.
MAX_TOKENS = int(os.environ.get("NEWS_AI_MAX_TOKENS", "2048"))
TIMEOUT = float(os.environ.get("NEWS_AI_TIMEOUT", "120"))
OUT_PATH = os.path.join(config.BASE_DIR, "news_ai_ratings.json")

SYSTEM = (
    "You are a Pakistan-equities news classifier for PSX-listed companies. "
    "Judge ONLY the direct impact on the named company's share price at the "
    "next PSX session. Ignore generic macro chatter unless it clearly hits "
    "that specific stock. Routine results announcements and scheduled "
    "dividends are neutral unless the number itself is a surprise. If the "
    "headlines do not support a directional call, say neutral — do not "
    "manufacture a signal."
)

# Structured output: forces exactly the shape we parse, so no prose to pay for
# and no JSON-repair guesswork on the way back.
SCHEMA = {
    "type": "object",
    "additionalProperties": {
        "type": "object",
        "properties": {
            "rating": {"type": "string", "enum": sorted(news_glm.VALID)},
            "reason": {"type": "string", "maxLength": 200},
        },
        "required": ["rating", "reason"],
        "additionalProperties": False,
    },
}


def _build_prompt(by_sym):
    lines = ["Rate each symbol below. Return one entry per symbol, keyed by "
             "the exact ticker, with a rating and a reason of at most one "
             "short clause.", ""]
    for sym, titles in by_sym.items():
        lines.append(f"{sym}:")
        lines.extend(f"- {t}" for t in titles)
        lines.append("")
    return "\n".join(lines)


def _call_claude(prompt, client):
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    # A refusal returns HTTP 200 with no usable content — treat it as no
    # ratings rather than letting a KeyError look like a network fault.
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined to classify this batch")
    text = "".join(b.text for b in resp.content if b.type == "text")
    usage = resp.usage
    log.info("in=%d out=%d tokens", usage.input_tokens, usage.output_tokens)
    return json.loads(text)


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping Claude news ratings")
        return 0

    by_sym = news_glm._collect_headlines()
    if not by_sym:
        log.info("No credible headlines to rate — skipping call")
        return 0

    log.info("Rating %d symbols with %s", len(by_sym), MODEL)
    client = anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT)
    try:
        raw = _call_claude(_build_prompt(by_sym), client)
    except anthropic.AuthenticationError:
        log.error("ANTHROPIC_API_KEY rejected (401) — fix the repo secret")
        return 1
    except anthropic.RateLimitError as e:
        log.error("rate limited: %s", e)
        return 1
    except Exception as e:
        log.error("Claude call failed: %s", e)
        return 1

    ratings = news_glm._sanitize(raw, set(by_sym.keys()))
    if not ratings:
        log.warning("no valid ratings returned — writing empty file")

    payload = {"as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "provider": "anthropic", "model": MODEL,
               "count": len(ratings), "ratings": ratings}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    log.info("Wrote %d ratings -> %s", len(ratings), OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
