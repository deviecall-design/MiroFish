"""Turn a finished simulation's posts into {bias, conviction}.

Same aggregate as the trader's persona council: bias is the mean stance in
[-1, 1]; conviction is |bias| discounted by dispersion, in [0, 1].
"""

import json
import math
import re
from typing import Any, Dict, Iterable, List, Optional

TEXT_ACTIONS = {"CREATE_POST", "CREATE_COMMENT", "QUOTE_POST", "REPOST"}

_BULL = {
    "buy", "buying", "bought", "long", "bullish", "moon", "rally", "breakout", "upside", "accumulate",
    "accumulating", "undervalued", "strong", "follow", "front-run", "frontrun", "calls", "rip", "higher",
    "beat", "surge", "momentum", "conviction", "add", "adding", "support",
}
_BEAR = {
    "sell", "selling", "sold", "short", "bearish", "dump", "crash", "fade", "fading", "overvalued",
    "overbought", "bubble", "weak", "downside", "puts", "lower", "trap", "exit", "risk", "caution",
    "skeptical", "profit-taking", "top", "resistance", "drop",
}


def aggregate(stances: List[float]) -> Dict[str, float]:
    if not stances:
        return {"bias": 0.0, "conviction": 0.0}
    s = [max(-1.0, min(1.0, float(x))) for x in stances]
    bias = sum(s) / len(s)
    spread = math.sqrt(sum((x - bias) ** 2 for x in s) / len(s))
    conviction = max(0.0, min(1.0, abs(bias) * (1 - spread)))
    return {"bias": round(bias, 4), "conviction": round(conviction, 4)}


def post_texts(actions: Iterable[Dict[str, Any]]) -> List[str]:
    out = []
    for a in actions:
        if a.get("action_type") not in TEXT_ACTIONS or not a.get("success", True):
            continue
        args = a.get("action_args") or {}
        text = args.get("content") or args.get("quote_content") or args.get("text") or ""
        if isinstance(text, str) and text.strip():
            out.append(text.strip()[:600])
    return out


def lexicon_stance(text: str) -> float:
    words = re.findall(r"[a-z][a-z\-]+", text.lower())
    bull = sum(1 for w in words if w in _BULL)
    bear = sum(1 for w in words if w in _BEAR)
    if bull == bear:
        return 0.0
    return (bull - bear) / (bull + bear)


def distill_lexicon(texts: List[str]) -> Dict[str, Any]:
    stances = [lexicon_stance(t) for t in texts]
    return {**aggregate(stances), "method": "lexicon", "stances": stances}


def parse_stances(raw: str, n: int) -> Optional[List[float]]:
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        arr = json.loads(raw[start : end + 1])
    except ValueError:
        return None
    vals = []
    for v in arr:
        if isinstance(v, dict):
            v = v.get("stance")
        if isinstance(v, (int, float)) and math.isfinite(v):
            vals.append(max(-1.0, min(1.0, float(v))))
    if len(vals) < max(1, n // 2):
        return None
    return vals[:n]


def distill_llm(texts: List[str], instrument_hint: str, chat) -> Optional[Dict[str, Any]]:
    """One bounded LLM call scoring every post. `chat(messages) -> str` is injected."""
    if not texts:
        return None
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts[:120]))
    messages = [
        {
            "role": "system",
            "content": (
                "You score social posts from a simulated market crowd. For each numbered post, give the "
                "author's stance on the instrument over the next few days: -1.0 strongly fade/short, "
                "+1.0 strongly follow/long, 0 no view. Reply with ONLY a JSON array of numbers, one per post, in order."
            ),
        },
        {"role": "user", "content": f"Instrument / bulletin:\n{instrument_hint[:800]}\n\nPosts:\n{numbered}"},
    ]
    raw = chat(messages)
    stances = parse_stances(raw or "", min(len(texts), 120))
    if stances is None:
        return None
    return {**aggregate(stances), "method": "llm", "stances": stances}
