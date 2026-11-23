"""
test_pipeline.py  -  "The safety checks"

WHAT THIS FILE DOES (in plain words)
------------------------------------
Automatic tests: small experiments that prove the program behaves correctly. Run them with
    python -m pytest -q
They use a FAKE AI (a tiny stand-in function), so they need no API key, cost nothing and
give the same result every time. If someone later changes the code and breaks a rule, a test
turns red and tells them immediately.
"""
import pandas as pd
import pytest
from langchain_core.runnables import RunnableLambda  # lets us wrap a plain function as a fake "chain"

from reviewlens.analytics import compute_stats, render_report
from reviewlens.pipeline import CSVValidationError, analyze_reviews, to_excel_csv, validate_csv
from reviewlens.schema import ReviewAnalysis, ThemeItem, WeeklyInsights


def make_df():
    """A tiny 5-row spreadsheet with problems on purpose: row 'c' is repeated, row 'd' has blank text."""
    return pd.DataFrame({
        "review_id": ["a", "b", "c", "c", "d"],
        "date": ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-03", "2026-10-04"],
        "platform": ["Google", "Swiggy", "Zomato", "Zomato", "Google"],
        "rating": [5, 1, 3, 3, 2],
        "review_text": ["great biryani", "food poisoning", "ok", "ok", "  "],
    })


def good(sent="negative", cat="delivery", urg="high"):
    """Build a perfectly valid AI answer, to be returned by the fake AI."""
    return ReviewAnalysis(sentiment=sent, category=cat, urgency=urg, language="English",
                          summary="s", suggested_reply="r")


def test_validate_drops_empty_and_duplicates():
    """The blank-text row and the repeated id must be removed, leaving a, b, c."""
    df, info = validate_csv(make_df())
    assert list(df["review_id"]) == ["a", "b", "c"]
    assert info["duplicates"] == 1


def test_validate_missing_column():
    """A file without the 'platform' column must be rejected with an error, not crash later."""
    with pytest.raises(CSVValidationError):
        validate_csv(make_df().drop(columns=["platform"]))


def test_retry_then_success_and_needs_review():
    """Fake AI behaviour per review:
         'great biryani'  -> correct on the first try
         'food poisoning' -> fails once, then correct (proves automatic retry works)
         'ok'             -> always garbage (proves it ends as 'needs review' after all retries)
    """
    df, _ = validate_csv(make_df())
    calls = {}  # counts how many times each review was sent

    def fake(inp):
        key = inp["review_text"]
        calls[key] = calls.get(key, 0) + 1
        if key == "great biryani":
            return good("positive", "food_quality", "low")
        if key == "food poisoning":
            if calls[key] < 2:  # first call fails, second succeeds
                raise ValueError("bad output")
            return good()
        return "garbage"  # never a valid answer

    out = analyze_reviews(df, RunnableLambda(fake), max_concurrency=2, max_retries=2)
    assert calls["food poisoning"] == 2   # asked twice: first failed, retry worked
    assert calls["ok"] == 3               # first attempt + 2 retries, then gave up
    assert out.loc[2, "sentiment"] == "needs review"
    assert out.loc[1, "urgency"] == "high"


def test_stats_and_report_numbers_from_pandas():
    """With 1 positive and 2 negative reviews, the percentages must be 33% and 67%,
    and the report must quote the pandas count (2), not anything the AI said."""
    df, _ = validate_csv(make_df())
    df["sentiment"] = ["positive", "negative", "negative"]
    df["category"] = ["food_quality", "delivery", "delivery"]
    df["urgency"] = ["low", "high", "medium"]
    df["language"] = "English"
    df["summary"] = "s"
    df["suggested_reply"] = "r"
    stats = compute_stats(df)
    assert stats["sentiment_pct"] == {"positive": 33, "neutral": 0, "negative": 67}
    assert stats["high_urgency"] == 1
    ins = WeeklyInsights(top_complaints=[ThemeItem(category="delivery", theme="Late", detail="x")],
                         top_praises=[], action_items=["a", "b", "c"])
    assert "2 negative delivery review(s)" in render_report(stats, ins)


def test_csv_export_has_bom():
    """The exported file must start with the invisible BOM marker so Excel shows Tamil correctly."""
    df, _ = validate_csv(make_df())
    assert to_excel_csv(df).startswith(b"\xef\xbb\xbf")


# ---------------------------------------------------------------------------
# STRETCH GOAL TESTS: reply language, week-over-week trend, history, weekly e-mail
# ---------------------------------------------------------------------------
def _week_df(sentiments, start="2026-10-03", ratings=None):
    """Build an already-analysed table (like the AI's output) so trend maths can be tested without any AI."""
    n = len(sentiments)
    return pd.DataFrame({
        "review_id": [f"x{i}" for i in range(n)],
        "date": pd.date_range(start, periods=n),
        "platform": "Google", "rating": ratings or [3] * n,
        "sentiment": sentiments, "category": "delivery",
        "urgency": ["high" if s == "negative" else "low" for s in sentiments],
        "language": "English", "summary": "s", "suggested_reply": "r",
    })


def test_reply_language_rule(monkeypatch):
    """Default prompt tells the AI to answer in the customer's language; 'english' switches it back."""
    from reviewlens.chains import review_system_prompt
    monkeypatch.delenv("REVIEWLENS_REPLY_LANGUAGE", raising=False)
    assert "SAME language" in review_system_prompt()
    assert "__REPLY_LANGUAGE_RULE__" not in review_system_prompt()
    monkeypatch.setenv("REVIEWLENS_REPLY_LANGUAGE", "english")
    assert "SAME language" not in review_system_prompt()
    monkeypatch.setenv("REVIEWLENS_REPLY_LANGUAGE", "klingon")
    with pytest.raises(RuntimeError):
        review_system_prompt()


def test_trend_numbers_and_arrows():
    """Last week 1 of 4 negative (25%); this week 3 of 4 (75%) -> +50 pts, worse."""
    from reviewlens.analytics import arrow, compute_trend
    last = compute_stats(_week_df(["negative", "positive", "positive", "positive"], "2026-09-26"))
    this = compute_stats(_week_df(["negative", "negative", "negative", "positive"]))
    t = compute_trend(this, last)
    assert t["negative_pct"] == 50 and t["high_urgency"] == 2 and t["negative_by_category"]["delivery"] == 2
    assert arrow(50, up_is_good=False, unit=" pts") == "▲ +50 pts (worse)"
    assert arrow(-2, up_is_good=False) == "▼ -2 (better)"
    assert arrow(0) == "► no change"


def test_history_picks_previous_week_only(tmp_path):
    """Saved weeks are found by date; the same week (overlapping) is never used as 'last week'."""
    from reviewlens.analytics import load_previous_stats, save_history
    last = compute_stats(_week_df(["negative", "positive"], "2026-09-26"))
    this = compute_stats(_week_df(["negative", "negative"], "2026-10-03"))
    assert load_previous_stats(this, tmp_path) is None            # nothing saved yet
    save_history(last, tmp_path)
    save_history(this, tmp_path)                                  # saving this week must not make it its own 'previous'
    prev = load_previous_stats(this, tmp_path)
    assert prev["total"] == 2 and prev["date_to"] == last["date_to"]


def test_report_shows_trend_section():
    from reviewlens.analytics import compute_trend
    last = compute_stats(_week_df(["negative", "positive"], "2026-09-26"))
    this = compute_stats(_week_df(["negative", "negative"], "2026-10-03"))
    ins = WeeklyInsights(top_complaints=[ThemeItem(category="delivery", theme="Late", detail="x")],
                         top_praises=[], action_items=["a", "b", "c"])
    text = render_report(this, ins, compute_trend(this, last))
    assert "TREND vs previous period" in text and "vs last week" in text
    assert "TREND" not in render_report(this, ins)                # no trend section without an earlier week


def test_run_analysis_and_email(tmp_path, monkeypatch):
    """End-to-end with fake AI: tagged table, report with numbers, e-mail with two attachments."""
    from reviewlens import analytics
    from reviewlens.weekly import build_email, run_analysis
    monkeypatch.setattr(analytics, "HISTORY_DIR", tmp_path)       # keep test data out of the real history folder
    monkeypatch.setattr("reviewlens.weekly.save_history", lambda s: analytics.save_history(s, tmp_path))
    monkeypatch.setattr("reviewlens.weekly.load_previous_stats", lambda s: analytics.load_previous_stats(s, tmp_path))
    df, _ = validate_csv(make_df())
    review_chain = RunnableLambda(lambda inp: good())
    report_chain = RunnableLambda(lambda inp: WeeklyInsights(
        top_complaints=[ThemeItem(category="delivery", theme="Late", detail="x")], top_praises=[],
        action_items=["a", "b", "c"]))
    res = run_analysis(df, review_chain, report_chain, concurrency=2)
    assert res["error"] is None and "3 negative delivery review(s)" in res["report"]
    msg = build_email(res, "from@x.com", ["to@x.com"])
    assert "ReviewLens weekly report" in msg["Subject"]
    assert sorted(a.get_filename() for a in msg.iter_attachments()) == ["reviews_enriched.csv", "weekly_report.txt"]


def test_language_label_is_corrected_by_script():
    """Tamil letters always mean Tamil; an AI 'Tamil' label on Latin-letter text becomes Tanglish."""
    from reviewlens.pipeline import has_tamil_script
    df = pd.DataFrame({"review_id": ["a", "b", "c"], "date": pd.to_datetime(["2026-10-01"] * 3),
                       "platform": "Google", "rating": 3,
                       "review_text": ["Delivery romba late", "டெலிவரி தாமதம்", "Good food"]})
    seen = {}

    def fake(inp):
        seen[inp["review_text"]] = inp["script"]                    # the hint the AI is given
        lang = "Tamil" if inp["review_text"] != "Good food" else "English"   # AI wrongly says Tamil for row a
        return ReviewAnalysis(sentiment="negative", category="delivery", urgency="low", language=lang,
                              summary="s", suggested_reply="r")

    out = analyze_reviews(df, RunnableLambda(fake), max_concurrency=1, max_retries=0)
    assert list(out["language"]) == ["Tanglish", "Tamil", "English"]
    assert seen["Delivery romba late"] == "Latin letters" and seen["டெலிவரி தாமதம்"] == "Tamil letters"
    assert has_tamil_script("டெலிவரி") and not has_tamil_script("hello")


def test_send_email_uses_tls_login_and_missing_settings_are_reported(monkeypatch):
    """The sender must encrypt (STARTTLS), log in and send; missing .env settings give a clear error."""
    import smtplib
    from email.message import EmailMessage
    from reviewlens.weekly import send_email, smtp_settings
    log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None): log.append(("connect", host, port))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): log.append("starttls")
        def login(self, u, p): log.append(("login", u))
        def send_message(self, m): log.append("sent")

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    send_email(EmailMessage(), {"host": "h", "port": 587, "user": "u", "password": "p"})
    assert log == [("connect", "h", 587), "starttls", ("login", "u"), "sent"]
    for k in ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "REPORT_TO"]:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        smtp_settings()
