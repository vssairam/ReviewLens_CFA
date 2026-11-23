"""
analytics.py  -  "The calculator and report writer"

WHAT THIS FILE DOES (in plain words)
------------------------------------
After every review has been tagged, this file:

  1. compute_stats    - COUNTS things with pandas: how many positive/neutral/negative reviews,
                        which categories have most complaints, how many are HIGH urgency, etc.
  2. generate_insights- hands those exact numbers, plus one-line summaries of the reviews, to the
                        report AI, which names the main complaint/praise themes and 3 actions.
  3. render_report    - prints the final report as plain text, pulling every number from step 1.

WHY THE AI DOES NOT DO THE COUNTING
Language models are unreliable at arithmetic. So the program does all the maths and the AI only
does what it is good at: reading many sentences and spotting patterns. This guarantees the
numbers in the report always match the table exactly.

This is the "reduce" half of "map then reduce": many per-review results are squeezed into ONE report.
"""
import json
from pathlib import Path

import pandas as pd

from .schema import NEEDS_REVIEW, SENTIMENTS, WeeklyInsights

# To keep the report AI's input small even for a huge week, we send at most this many summaries
# per group (negative / positive). The most urgent reviews are always kept first.
MAX_SUMMARIES = 300


def compute_stats(df: pd.DataFrame) -> dict:
    """Count everything the report needs. Returns a dictionary of numbers."""
    # Reviews the AI failed on ("needs review") are left out of the sentiment maths,
    # otherwise they would distort the percentages.
    ok = df[df["sentiment"] != NEEDS_REVIEW]
    total = len(df)
    n_ok = len(ok)
    # Count each sentiment; reindex makes sure all three appear even if one has zero reviews.
    counts = ok["sentiment"].value_counts().reindex(SENTIMENTS, fill_value=0)
    # Percentages rounded to whole numbers (guarding against dividing by zero).
    pct = {s: (round(100 * counts[s] / n_ok) if n_ok else 0) for s in SENTIMENTS}
    neg = ok[ok["sentiment"] == "negative"]   # only the negative reviews
    pos = ok[ok["sentiment"] == "positive"]   # only the positive reviews
    return {
        "total": total,
        "analysed": n_ok,
        "needs_review": total - n_ok,
        "date_from": df["date"].min(),          # earliest review date in the file
        "date_to": df["date"].max(),            # latest review date in the file
        "sentiment_counts": {s: int(counts[s]) for s in SENTIMENTS},
        "sentiment_pct": pct,
        "category_counts": ok["category"].value_counts().to_dict(),
        "urgency_counts": ok["urgency"].value_counts().to_dict(),
        "negative_by_category": neg["category"].value_counts().to_dict(),   # e.g. {"delivery": 34, ...}
        "positive_by_category": pos["category"].value_counts().to_dict(),
        "negative_by_platform": neg["platform"].value_counts().to_dict(),   # e.g. {"Swiggy": 20, ...}
        "high_urgency": int((ok["urgency"] == "high").sum()),
        "avg_rating": round(float(df["rating"].mean()), 2) if df["rating"].notna().any() else None,
    }


# ---------------------------------------------------------------------------
# STRETCH GOAL - compare this week with last week (trend arrows)
# Each analysed week's numbers are saved in the "history" folder. The next week's run finds the
# most recent earlier week there and shows how every number moved. No AI is involved: this is
# pure arithmetic on pandas counts.
# ---------------------------------------------------------------------------
HISTORY_DIR = Path(__file__).resolve().parent.parent / "history"
_SAVED_KEYS = ["total", "analysed", "needs_review", "sentiment_counts", "sentiment_pct", "negative_by_category",
               "positive_by_category", "high_urgency", "avg_rating"]


def save_history(stats: dict, folder: Path = HISTORY_DIR) -> Path:
    """Save one week's numbers as a small JSON file named after the week's last day."""
    folder.mkdir(parents=True, exist_ok=True)
    data = {k: stats[k] for k in _SAVED_KEYS}
    data["date_from"], data["date_to"] = f"{stats['date_from']:%Y-%m-%d}", f"{stats['date_to']:%Y-%m-%d}"
    path = folder / f"week_ending_{data['date_to']}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _load_stats_file(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["date_from"], data["date_to"] = pd.Timestamp(data["date_from"]), pd.Timestamp(data["date_to"])
    return data


def load_previous_stats(current: dict, folder: Path = HISTORY_DIR) -> dict | None:
    """Find the most recent saved week that ended BEFORE the current week began (None if there is none).
    A week that overlaps the current one (e.g. the same file analysed twice) is never used."""
    if not folder.exists():
        return None
    best = None
    for f in folder.glob("week_ending_*.json"):
        try:
            old = _load_stats_file(f)
        except (ValueError, KeyError, OSError):
            continue  # ignore a damaged file rather than crash
        if old["date_to"] < current["date_from"] and (best is None or old["date_to"] > best["date_to"]):
            best = old
    return best


def stats_from_enriched_csv(df: pd.DataFrame) -> dict:
    """Rebuild the numbers from a previously exported 'enriched' CSV (so last week need not be re-analysed)."""
    need = {"date", "sentiment", "category", "urgency", "platform", "rating"}
    if not need.issubset(df.columns):
        raise ValueError("That file is not an enriched ReviewLens CSV (missing: "
                         f"{', '.join(sorted(need - set(df.columns)))}).")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        raise ValueError("The previous-week file has no valid rows.")
    return compute_stats(df)


def compute_trend(cur: dict, prev: dict) -> dict:
    """Difference between this week and the previous one. Every value is (this week - last week)."""
    def d(a, b):
        return None if a is None or b is None else round(a - b, 2)

    cats = set(cur["negative_by_category"]) | set(prev["negative_by_category"])
    pcats = set(cur["positive_by_category"]) | set(prev["positive_by_category"])
    return {
        "prev_from": prev["date_from"], "prev_to": prev["date_to"],
        "total": cur["total"] - prev["total"],
        "negative_pct": cur["sentiment_pct"]["negative"] - prev["sentiment_pct"]["negative"],
        "positive_pct": cur["sentiment_pct"]["positive"] - prev["sentiment_pct"]["positive"],
        "high_urgency": cur["high_urgency"] - prev["high_urgency"],
        "avg_rating": d(cur["avg_rating"], prev["avg_rating"]),
        "negative_by_category": {c: cur["negative_by_category"].get(c, 0) - prev["negative_by_category"].get(c, 0) for c in cats},
        "positive_by_category": {c: cur["positive_by_category"].get(c, 0) - prev["positive_by_category"].get(c, 0) for c in pcats},
    }


def arrow(delta, up_is_good: bool | None = None, unit: str = "") -> str:
    """Turn a change into text like '▲ +5' or '▼ -3 pts'; adds (better)/(worse) when we know which is which."""
    if delta is None:
        return "n/a"
    if delta == 0:
        return "► no change"
    sym = "▲" if delta > 0 else "▼"
    text = f"{sym} {delta:+g}{unit}"
    if up_is_good is not None:
        text += " (better)" if (delta > 0) == up_is_good else " (worse)"
    return text


def _stats_text(s: dict) -> str:
    """Write the statistics as plain text lines, to paste into the report AI's instructions."""
    return (
        f"Period: {s['date_from']:%d %b} to {s['date_to']:%d %b %Y}\n"
        f"Total reviews: {s['total']} (needs manual review: {s['needs_review']})\n"
        f"Sentiment: {s['sentiment_counts']}\nNegative by category: {s['negative_by_category']}\n"
        f"Negative by platform: {s['negative_by_platform']}\nPositive by category: {s['positive_by_category']}\n"
        f"High urgency reviews: {s['high_urgency']}"
    )


def _summaries(df: pd.DataFrame) -> str:
    """Turn a group of reviews into one line each: 'category | platform | summary'."""
    if df.empty:
        return "(none)"
    # Sort so HIGH urgency comes first; if we have to cut the list, the important ones survive.
    order = {"high": 0, "medium": 1, "low": 2}
    df = df.assign(_o=df["urgency"].map(order)).sort_values("_o").head(MAX_SUMMARIES)
    return "\n".join(f"{r.category} | {r.platform} | {r.summary}" for r in df.itertuples())


def generate_insights(df: pd.DataFrame, report_chain) -> tuple[dict, WeeklyInsights]:
    """Run the 'reduce' step: numbers from pandas + summaries -> AI -> themes and action items."""
    stats = compute_stats(df)
    ok = df[df["sentiment"] != NEEDS_REVIEW]
    # .invoke runs the report chain ONCE with these three pieces of text filled in.
    insights = report_chain.invoke({
        "stats": _stats_text(stats),
        "negatives": _summaries(ok[ok["sentiment"] == "negative"]),
        "positives": _summaries(ok[ok["sentiment"] == "positive"]),
    })
    return stats, insights


def render_report(stats: dict, ins: WeeklyInsights, trend: dict | None = None) -> str:
    """Assemble the final plain-text report the manager reads.

    Every NUMBER here comes from pandas (the 'stats' dictionary). The AI supplied only the theme
    names, their one-line details and the action items.
    """
    p, c = stats["sentiment_pct"], stats["sentiment_counts"]
    lines = [
        f"WEEKLY FEEDBACK REPORT  |  {stats['date_from']:%d %b} to {stats['date_to']:%d %b %Y}",
        f"Total reviews: {stats['total']}   Positive {p['positive']}% ({c['positive']})   "
        f"Neutral {p['neutral']}% ({c['neutral']})   Negative {p['negative']}% ({c['negative']})",
    ]
    # Be honest if some reviews could not be analysed.
    if stats["needs_review"]:
        lines.append(f"Note: {stats['needs_review']} review(s) could not be analysed and are marked 'needs review'.")
    lines += ["", "TOP COMPLAINTS"]
    for i, t in enumerate(ins.top_complaints[:3], 1):
        # The count shown = how many negative reviews pandas found in that theme's category.
        n = stats["negative_by_category"].get(t.category, 0)
        tail = f"  {arrow(trend['negative_by_category'].get(t.category, 0), up_is_good=False)} vs last week" if trend else ""
        lines.append(f"  {i}. {t.theme} ... {n} negative {t.category} review(s)  ({t.detail}){tail}")
    lines += ["", "TOP PRAISE"]
    for i, t in enumerate(ins.top_praises[:3], 1):
        n = stats["positive_by_category"].get(t.category, 0)
        tail = f"  {arrow(trend['positive_by_category'].get(t.category, 0), up_is_good=True)} vs last week" if trend else ""
        lines.append(f"  {i}. {t.theme} ... {n} positive {t.category} review(s)  ({t.detail}){tail}")
    lines += ["", f"URGENT: {stats['high_urgency']} review(s) need a reply within 24 hours"]
    if trend:  # STRETCH GOAL: week-over-week arrows
        lines += ["", f"TREND vs previous period ({trend['prev_from']:%d %b} to {trend['prev_to']:%d %b %Y})",
                  f"  Total reviews : {arrow(trend['total'])}",
                  f"  Negative share: {arrow(trend['negative_pct'], up_is_good=False, unit=' pts')}",
                  f"  Positive share: {arrow(trend['positive_pct'], up_is_good=True, unit=' pts')}",
                  f"  HIGH urgency  : {arrow(trend['high_urgency'], up_is_good=False)}",
                  f"  Average rating: {arrow(trend['avg_rating'], up_is_good=True)}"]
    lines += ["", "ACTION ITEMS"]
    for i, a in enumerate(ins.action_items[:3], 1):
        lines.append(f"  {i}. {a}")
    return "\n".join(lines)
