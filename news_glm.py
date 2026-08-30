"""Rate verified article-backed news with GLM and write production AI ratings."""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import requests

import news_digest

log = logging.getLogger("news_glm")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

GLM_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_MODEL = os.environ.get("GLM_MODEL", "glm-4.7-flash")
GLM_TIMEOUT = int(os.environ.get("GLM_TIMEOUT", "75"))
GLM_ATTEMPTS = 2
GLM_TEXT_CHARS = int(os.environ.get("GLM_TEXT_CHARS", "1600"))
GLM_MAX_ITEMS_PER_KEY = int(os.environ.get("GLM_MAX_ITEMS_PER_KEY", "4"))
OUT_PATH = os.path.join(os.path.dirname(__file__), "news_ai_ratings.json")

VALID_RATINGS = {"highly_positive", "positive", "neutral", "negative",
                 "highly_negative"}
CAUSALITY = {"causal", "correlated", "noise"}
HORIZONS = {"single_session", "multi_session"}

SYSTEM = (
    "You classify verified Pakistan-equities news for decision support. Use only "
    "the supplied publisher text. Never infer missing facts. Causal requires a "
    "stated mechanism to cash flow or valuation; correlated is related but lacks "
    "that mechanism; noise has no defensible mechanism. Prefer neutral/noise "
    "when evidence is ambiguous. Return JSON only."
)


def _build_prompt(digest):
    lines = [
        SYSTEM, "",
        "Return exactly this JSON object: "
        '{"company":{"SYMBOL":{"rating":"positive","reason":"short evidence-bound reason",'
        '"causality":"causal","confidence":0.0,"horizon":"single_session"}},'
        '"sector":{"SECTOR":{"rating":"neutral","reason":"short evidence-bound reason",'
        '"causality":"noise","confidence":0.0,"horizon":"single_session"}}}.',
        "Rate every supplied key and no other key.",
    ]
    for group in ("company", "sector"):
        lines.append(f"\n{group.upper()}:")
        for key, items in (digest.get(group) or {}).items():
            lines.append(f"\n{key}:")
            for item in items[:GLM_MAX_ITEMS_PER_KEY]:
                lines.append(
                    f"- [{item.get('source')}; {item.get('published')}; "
                    f"depth={item.get('depth')}] {item.get('title')}\n"
                    f"  TEXT: {(item.get('text') or '[no publisher text]')[:GLM_TEXT_CHARS]}"
                )
    return "\n".join(lines)


def _call_glm(prompt, api_key):
    last_error = None
    for attempt in range(1, GLM_ATTEMPTS + 1):
        try:
            response = requests.post(
                GLM_ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={"model": GLM_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.1,
                      "max_tokens": 2048,
                      "thinking": {"type": "disabled"},
                      "response_format": {"type": "json_object"}},
                timeout=GLM_TIMEOUT,
            )
            response.raise_for_status()
            return json.loads(response.json()["choices"][0]["message"]["content"])
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            log.warning("GLM attempt %d/%d network failure: %s",
                        attempt, GLM_ATTEMPTS, exc)
        except (KeyError, TypeError, ValueError, requests.HTTPError) as exc:
            raise RuntimeError(f"GLM request failed: {exc}") from exc
    raise RuntimeError(f"GLM request timed out: {last_error}")


def _sanitize_group(raw, evidence):
    clean = {}
    for key, verdict in (raw or {}).items():
        if key not in evidence or not isinstance(verdict, dict):
            continue
        rating = str(verdict.get("rating") or "").lower().replace("-", "_")
        causality = verdict.get("causality")
        confidence = verdict.get("confidence")
        horizon = verdict.get("horizon")
        if (rating not in VALID_RATINGS or causality not in CAUSALITY
                or horizon not in HORIZONS or isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0.0 <= confidence <= 1.0):
            continue
        items = evidence[key]
        sources = list(dict.fromkeys(i.get("url") for i in items if i.get("url")))
        published = list(dict.fromkeys(
            i.get("published") for i in items if i.get("published")))
        if not sources or not published:
            continue
        clean[key] = {
            "rating": rating,
            "reason": str(verdict.get("reason") or "")[:200],
            "causality": causality,
            "confidence": float(confidence),
            "horizon": horizon,
            "text_depth": "full" if any(i.get("depth") == "full" for i in items)
                          else "headline",
            "sources": sources,
            "source_published": published,
        }
    return clean


def main():
    api_key = os.environ.get("GLM_API_KEY") or os.environ.get("ZHIPU_API_KEY")
    if not api_key:
        log.error("GLM_API_KEY not set")
        return 1
    digest = news_digest.build()
    if not digest.get("company") and not digest.get("sector"):
        log.error("digest contains no rateable company or sector evidence")
        return 1
    try:
        raw = _call_glm(_build_prompt(digest), api_key)
    except Exception as exc:
        log.error("GLM call failed: %s", exc)
        return 1
    ratings = _sanitize_group(raw.get("company"), digest["company"])
    sectors = _sanitize_group(raw.get("sector"), digest["sector"])
    if not ratings and not sectors:
        log.error("GLM returned no valid ratings")
        return 1
    payload = {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_fetched_at": digest.get("fetched_at"),
        "provider": "zhipu", "model": GLM_MODEL,
        "count": len(ratings), "sector_count": len(sectors),
        "ratings": ratings, "sectors": sectors,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    log.info("Wrote %d company and %d sector ratings", len(ratings), len(sectors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
