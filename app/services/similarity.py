"""Lightweight text similarity for vendor landing story blocks.

Uses TF-IDF over word unigrams + character 4-grams with cosine similarity.
No external deps (pure stdlib + math).

Purpose: ensure vendors produce *original* landing-page copy. When two
vendors' story text is too similar (copy-paste, shared AI output, etc.),
we want to surface the overlap and give the vendor a uniqueness score
they can improve.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, Optional


# ── Tokenization ──
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
    "for", "with", "from", "by", "is", "are", "was", "were", "be", "been",
    "being", "it", "this", "that", "these", "those", "our", "my", "your",
    "we", "i", "you", "they", "them", "us", "he", "she", "his", "her",
    "their", "its", "so", "as", "if", "than", "then", "also", "just",
    "here", "there", "have", "has", "had", "do", "does", "did", "can",
    "will", "would", "could", "should", "may", "might", "one", "each",
    "every", "some", "any", "all", "most", "more", "much", "many",
    "about", "over", "into", "out", "up", "down", "off", "too", "very",
}


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def _word_tokens(text: str) -> list[str]:
    return [w for w in (m.group(0).lower() for m in _WORD_RE.finditer(text))
            if w not in _STOPWORDS and len(w) > 2]


def _char_ngrams(text: str, n: int = 4) -> list[str]:
    t = _normalize(text)
    if len(t) < n:
        return []
    return [t[i:i + n] for i in range(len(t) - n + 1)]


def _features(text: str) -> Counter:
    """Combined feature bag: word unigrams (weight 1.0) + char 4-grams (weight 0.5)."""
    feats: Counter = Counter()
    for w in _word_tokens(text):
        feats[f"w:{w}"] += 1
    # char n-grams catch paraphrase/spacing variations; lower weight to
    # avoid swamping meaningful words
    for g in _char_ngrams(text, 4):
        feats[f"c:{g}"] += 0.5  # type: ignore[arg-type]
    return feats


# ── TF-IDF + cosine ──
def build_idf(docs: Iterable[str]) -> dict[str, float]:
    """Inverse-document-frequency over feature space."""
    df: Counter = Counter()
    total = 0
    for d in docs:
        total += 1
        seen = set(_features(d).keys())
        for term in seen:
            df[term] += 1
    if total == 0:
        return {}
    # smoothed idf: log((1+N)/(1+df)) + 1
    return {t: math.log((1 + total) / (1 + c)) + 1.0 for t, c in df.items()}


def tfidf_vector(text: str, idf: dict[str, float]) -> dict[str, float]:
    tf = _features(text)
    return {t: float(v) * idf.get(t, 1.0) for t, v in tf.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    # iterate over the smaller dict
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── Story-block aggregation ──
STORY_KEYS = ("origin", "specialty", "process", "values", "whats_new")


def flatten_story_blocks(blocks: Optional[dict]) -> str:
    """Join all story blocks into a single corpus string."""
    if not blocks:
        return ""
    parts: list[str] = []
    for k in STORY_KEYS:
        v = (blocks or {}).get(k)
        if v and isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return "\n\n".join(parts)


def vendor_corpus(
    tagline: Optional[str],
    meta_desc: Optional[str],
    about: Optional[str],
    story_blocks: Optional[dict],
) -> str:
    """Combine the vendor's originality-sensitive long-form text fields."""
    chunks = []
    for c in (tagline, meta_desc, about, flatten_story_blocks(story_blocks)):
        if c and str(c).strip():
            chunks.append(str(c).strip())
    return "\n\n".join(chunks)


# ── Uniqueness scoring ──
def uniqueness_score(
    target_text: str,
    other_texts: list[tuple[str, str]],  # [(vendor_name, text), ...]
) -> dict:
    """Return {score: 0-100 (higher = more unique), similar_to: [...], top_similarity: float}.

    Score mapping:
      - max_similarity 0.00 → 100
      - max_similarity 0.50 → 50
      - max_similarity ≥ 1.00 → 0
    We use a mild curve: score = max(0, round(100 * (1 - max_sim ** 0.8))).
    Vendors with similarity > 0.5 are surfaced as "similar_to".
    """
    if not target_text or not target_text.strip():
        return {
            "score": 0,
            "top_similarity": 0.0,
            "similar_to": [],
            "word_count": 0,
            "message": "Add story content to get a uniqueness score.",
        }

    # If no peer corpus → perfect score (or near), since originality is trivial
    peer_texts = [t for _, t in other_texts if t and t.strip()]
    word_count = len(_word_tokens(target_text))

    if not peer_texts:
        return {
            "score": 100,
            "top_similarity": 0.0,
            "similar_to": [],
            "word_count": word_count,
            "message": "No peers to compare against yet — you're the first.",
        }

    corpus = [target_text] + peer_texts
    idf = build_idf(corpus)
    target_vec = tfidf_vector(target_text, idf)

    sims: list[tuple[str, float]] = []
    for name, txt in other_texts:
        if not txt or not txt.strip():
            continue
        v = tfidf_vector(txt, idf)
        s = cosine(target_vec, v)
        sims.append((name, s))

    sims.sort(key=lambda x: x[1], reverse=True)
    max_sim = sims[0][1] if sims else 0.0
    # curve
    score = max(0, min(100, round(100 * (1 - max_sim ** 0.8))))
    similar_to = [
        {"vendor_name": n, "similarity": round(s, 3)}
        for n, s in sims[:3]
        if s >= 0.45
    ]
    return {
        "score": int(score),
        "top_similarity": round(float(max_sim), 3),
        "similar_to": similar_to,
        "word_count": word_count,
        "message": _score_message(score, max_sim, bool(similar_to)),
    }


def _score_message(score: int, max_sim: float, has_matches: bool) -> str:
    if score >= 85:
        return "Distinctive — your story stands out from other vendors."
    if score >= 65:
        return "Solid originality. A few tweaks could make it even more unique."
    if score >= 40:
        return ("Your story overlaps noticeably with at least one other vendor. "
                "Consider adding specific names, years, techniques, or personal details.") if has_matches \
               else "Consider adding more specific, personal details to stand out."
    return ("High overlap with another vendor detected. Rewrite with your "
            "own voice, specific examples, and unique details.")
