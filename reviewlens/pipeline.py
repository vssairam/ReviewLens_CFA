"""
pipeline.py  -  "The factory floor"

WHAT THIS FILE DOES (in plain words)
------------------------------------
It handles the journey of the uploaded spreadsheet:

  1. validate_csv    - check the spreadsheet is usable and tidy it up
                       (right columns? remove blank rows, duplicates, rows with unreadable dates).
  2. analyze_reviews - send every review to the AI (many at the same time, to save time),
                       check each answer, RE-ASK the AI when an answer is invalid,
                       and mark a review "needs review" if it still fails.
  3. to_excel_csv    - turn the final table into a download file that Excel opens correctly,
                       including Tamil letters.

"pandas" (imported as pd) is the Python library for working with spreadsheet-like tables
called DataFrames: rows = reviews, columns = review_id, date, platform, ...
"""
import os
from typing import Callable

import pandas as pd
from pydantic import ValidationError

from .schema import (
    CATEGORIES, LANGUAGES, NEEDS_REVIEW, REQUIRED_COLUMNS, SENTIMENTS, URGENCIES, ReviewAnalysis,
)

# The six columns the AI adds to each review.
AI_FIELDS = ["sentiment", "category", "urgency", "language", "summary", "suggested_reply"]

# For each AI column, the list of values we accept. Used to double-check the AI's answers.
ALLOWED = {"sentiment": SENTIMENTS, "category": CATEGORIES, "urgency": URGENCIES, "language": LANGUAGES}


class CSVValidationError(ValueError):
    """Raised when the uploaded file cannot be used (e.g. a required column is missing).
    The app catches it and shows the message to the user in plain language."""


def validate_csv(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Check the uploaded table and clean it. Returns (clean table, counts about what was removed)."""
    df = df.copy()  # work on a copy so the user's original data is never altered

    # Make column names forgiving: ignore capital letters and stray spaces ("Review_Text " -> "review_text").
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Stop immediately if any of the 5 required columns is absent.
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise CSVValidationError(f"Missing required column(s): {', '.join(missing)}")
    df = df[REQUIRED_COLUMNS]  # keep only the columns we need, in a fixed order
    total = len(df)            # remember how many rows we started with

    # Remove rows whose review text is empty or only spaces - nothing to analyse.
    df["review_text"] = df["review_text"].astype("string").str.strip()
    df = df[df["review_text"].notna() & (df["review_text"] != "")]

    # Remove rows with no review_id, then drop repeated ids (keep the first occurrence).
    df["review_id"] = df["review_id"].astype("string").str.strip()
    df = df[df["review_id"].notna() & (df["review_id"] != "")]
    dup = int(df["review_id"].duplicated().sum())  # how many repeats we are about to remove
    df = df.drop_duplicates("review_id")

    # Convert text to real dates / numbers. errors="coerce" turns unreadable values into "empty"
    # instead of crashing; rows with an unreadable date are then removed.
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        raise CSVValidationError("No valid rows found after removing empty/invalid rows.")
    df = df.reset_index(drop=True)  # renumber rows 0,1,2,... after the removals
    return df, {"rows_in": total, "rows_kept": len(df), "dropped": total - len(df), "duplicates": dup}


def _is_valid(result) -> bool:
    """Return True only if the AI's answer is a proper filled-in form with allowed values.

    (The leading underscore is a Python convention meaning 'internal helper, not for outside use'.)
    """
    if not isinstance(result, ReviewAnalysis):  # e.g. an error message or garbage text
        return False
    d = result.model_dump()  # turn the form into a simple dictionary
    # Every constrained box must hold an allowed word, and the two text boxes must not be blank.
    return all(d[k] in v for k, v in ALLOWED.items()) and bool(d["summary"].strip()) and bool(d["suggested_reply"].strip())


def has_tamil_script(text) -> bool:
    """True if the text contains any Tamil-script letter (Unicode block U+0B80 to U+0BFF)."""
    return any("஀" <= ch <= "௿" for ch in str(text))


def _fix_language(d: dict, text) -> dict:
    """Script is a fact the program can check, so it overrules the AI's language label when they disagree:
    Tamil letters present -> Tamil;  AI said Tamil but there are only Latin letters -> Tanglish."""
    if has_tamil_script(text):
        d["language"] = "Tamil"
    elif d["language"] == "Tamil":
        d["language"] = "Tanglish"
    return d


def _inputs(row) -> dict:
    """Pick what the AI needs from one spreadsheet row: platform, rating, review text and its writing system."""
    rating = "" if pd.isna(row["rating"]) else int(row["rating"])  # blank rating stays blank
    script = "Tamil letters" if has_tamil_script(row["review_text"]) else "Latin letters"
    return {"platform": row["platform"], "rating": rating, "review_text": row["review_text"], "script": script}


def analyze_reviews(
    df: pd.DataFrame,
    chain,
    max_concurrency: int | None = None,
    max_retries: int | None = None,
    batch_size: int = 25,
    on_progress: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """Send every review to the AI and return the table with 6 extra columns.

    Parameters in everyday terms:
      chain           - the AI assembly line built in chains.py
      max_concurrency - how many reviews may be sent at the same moment (more = faster, but the AI
                        company limits how fast you may ask, so we cap it)
      max_retries     - how many extra times to re-ask for a review whose answer was invalid
      batch_size      - reviews are processed in groups of this size so the progress bar can move
      on_progress     - optional function called after each group, used to update the progress bar
    """
    # Use the value given, otherwise the .env setting, otherwise a sensible default.
    max_concurrency = max_concurrency or int(os.getenv("REVIEWLENS_MAX_CONCURRENCY", "5"))
    max_retries = max_retries if max_retries is not None else int(os.getenv("REVIEWLENS_MAX_RETRIES", "2"))

    inputs = [_inputs(r) for _, r in df.iterrows()]  # one little dictionary per review
    results: list = [None] * len(inputs)             # one empty slot per review, filled as answers arrive
    pending = list(range(len(inputs)))               # positions of reviews still waiting for a valid answer

    # Round 0 is the first attempt; rounds 1, 2, ... are the automatic retries.
    for attempt in range(max_retries + 1):
        if not pending:      # everything already succeeded - stop early
            break
        still_bad: list[int] = []  # reviews that failed in THIS round
        for start in range(0, len(pending), batch_size):
            idx = pending[start:start + batch_size]  # the next group of review positions
            # chain.batch sends the whole group to the AI in parallel.
            # return_exceptions=True means a failure on one review is returned as an error object
            # instead of crashing the whole run.
            outs = chain.batch([inputs[i] for i in idx], config={"max_concurrency": max_concurrency},
                               return_exceptions=True)
            for i, out in zip(idx, outs):
                if isinstance(out, (Exception, ValidationError)) or not _is_valid(out):
                    still_bad.append(i)   # bad answer -> try again in the next round
                else:
                    results[i] = out      # good answer -> store it
            if on_progress and attempt == 0:  # move the progress bar (first round only)
                on_progress(min(start + batch_size, len(pending)), len(inputs))
        pending = still_bad  # only the failures go into the next round

    # Turn the stored answers into table rows. A slot still empty means every attempt failed,
    # so we fill it with the "needs review" label for a human to handle.
    rows = []
    for res, inp in zip(results, inputs):
        if res is None:
            rows.append({"sentiment": NEEDS_REVIEW, "category": NEEDS_REVIEW, "urgency": NEEDS_REVIEW,
                         "language": NEEDS_REVIEW, "summary": "Automatic analysis failed; please read manually.",
                         "suggested_reply": ""})
        else:
            rows.append(_fix_language(res.model_dump(), inp["review_text"]))
    # Glue the 6 new columns to the right of the original columns.
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(rows, columns=AI_FIELDS)], axis=1)


def to_excel_csv(df: pd.DataFrame) -> bytes:
    """Convert the table into the bytes of a CSV file that Excel opens correctly.

    "utf-8-sig" adds a tiny invisible marker at the start of the file (called a BOM). Without it,
    Excel often shows Tamil text as garbled symbols.
    """
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")  # plain date, no time-of-day
    return out.to_csv(index=False).encode("utf-8-sig")
