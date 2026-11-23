"""
weekly.py  -  "One button for the whole week"

WHAT THIS FILE DOES (in plain words)
------------------------------------
Runs the complete job for one week of reviews, from a cleaned table to a finished report:

    classify every review  ->  count (pandas)  ->  write report (AI)  ->  compare with last week

It is used by BOTH front doors of the program, so they always behave the same:
  * app.py                 - the web page a person clicks through
  * send_weekly_report.py  - the unattended script that e-mails the report every Monday

It also contains the helpers that build and send the e-mail (stretch goal 3).
"""
import os
import smtplib
from email.message import EmailMessage

import pandas as pd

from .analytics import (compute_stats, compute_trend, generate_insights, load_previous_stats, render_report,
                        save_history)
from .pipeline import analyze_reviews, to_excel_csv


def run_analysis(df: pd.DataFrame, review_chain, report_chain, prev_stats: dict | None = None,
                 concurrency: int | None = None, on_progress=None, save: bool = True) -> dict:
    """Analyse one validated week and return everything the screens and the e-mail need.

    prev_stats - last week's numbers if the caller already has them (e.g. an uploaded file).
                 If None, the most recent earlier week in the history folder is used, if any.
    save       - remember this week's numbers in the history folder so NEXT week can compare.
    Never raises because of the report step: if the report AI fails we still return the tagged table.
    """
    enriched = analyze_reviews(df, review_chain, max_concurrency=concurrency, on_progress=on_progress)
    stats = compute_stats(enriched)
    trend, insights, error = None, None, None
    prev = prev_stats or load_previous_stats(stats)
    if prev:
        trend = compute_trend(stats, prev)
    try:
        _, insights = generate_insights(enriched, report_chain)
        report = render_report(stats, insights, trend)
    except Exception as e:  # keep the table even if the report fails
        error = str(e)
        report = f"Report could not be generated: {e}"
    if save:
        save_history(stats)
    return {"enriched": enriched, "stats": stats, "insights": insights, "trend": trend,
            "report": report, "error": error}


# ---------------------------------------------------------------------------
# E-mail (STRETCH GOAL 3: send the weekly report automatically every Monday)
# Settings come from the .env file; nothing secret is written in the code.
# ---------------------------------------------------------------------------
def build_email(result: dict, sender: str, recipients: list[str]) -> EmailMessage:
    """Create the e-mail: report text in the body, report + enriched CSV attached."""
    stats = result["stats"]
    msg = EmailMessage()
    msg["Subject"] = f"ReviewLens weekly report | {stats['date_from']:%d %b} to {stats['date_to']:%d %b %Y}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(result["report"] + "\n\nThe full tagged table (with suggested replies) is attached as a CSV "
                    "that opens in Excel.\n-- ReviewLens")
    msg.add_attachment(result["report"].encode("utf-8"), maintype="text", subtype="plain", filename="weekly_report.txt")
    msg.add_attachment(to_excel_csv(result["enriched"]), maintype="text", subtype="csv", filename="reviews_enriched.csv")
    return msg


def smtp_settings() -> dict:
    """Read the mail settings from the environment and complain clearly if something is missing."""
    cfg = {"host": os.getenv("SMTP_HOST", ""), "port": int(os.getenv("SMTP_PORT", "587")),
           "user": os.getenv("SMTP_USER", ""), "password": os.getenv("SMTP_PASSWORD", ""),
           "sender": os.getenv("REPORT_FROM", "") or os.getenv("SMTP_USER", ""),
           "to": [a.strip() for a in os.getenv("REPORT_TO", "").split(",") if a.strip()]}
    missing = [n for n, v in [("SMTP_HOST", cfg["host"]), ("SMTP_USER", cfg["user"]), ("SMTP_PASSWORD", cfg["password"]),
                              ("REPORT_TO", cfg["to"])] if not v]
    if missing:
        raise RuntimeError(f"E-mail not configured. Set in .env: {', '.join(missing)} (see .env.example).")
    return cfg


def send_email(msg: EmailMessage, cfg: dict) -> None:
    """Send through the SMTP server using an encrypted connection (STARTTLS, or SSL on port 465)."""
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as s:
            s.starttls()
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
