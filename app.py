"""
app.py  -  "The screen the manager sees"

WHAT THIS FILE DOES (in plain words)
------------------------------------
This is the web page. Run it with:   streamlit run app.py
Streamlit turns this Python file into a web page: every st.something(...) line draws one
element (a button, a chart, a table). Each time the user clicks something, Streamlit runs
the file again from top to bottom - that is why results are kept in "st.session_state"
(the page's memory) so they do not vanish on every click.

THE PAGE FLOW
  Sidebar : upload CSV -> click "Analyse reviews"
  Step 1  : read + validate the file          (pipeline.validate_csv)
  Step 2-3: tag, count, write report, compare with last week   (weekly.run_analysis)
  Tabs    : Dashboard (charts + HIGH-urgency filter) | Weekly report | Table + CSV download
"""
import pandas as pd
import plotly.express as px   # chart library
import streamlit as st

from reviewlens.analytics import stats_from_enriched_csv
from reviewlens.chains import build_report_chain, build_review_chain
from reviewlens.pipeline import CSVValidationError, analyze_reviews, to_excel_csv, validate_csv
from reviewlens.schema import NEEDS_REVIEW
from reviewlens.weekly import run_analysis

# Browser-tab title and full-width layout.
st.set_page_config(page_title="ReviewLens", page_icon="🔍", layout="wide")
st.title("🔍 ReviewLens")
st.caption("Turn a week of customer reviews into tagged insights and a 5-minute report.")

# ---------------------------------------------------------------------------
# SIDEBAR: where the user uploads the file and starts the analysis.
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("1. Upload")
    file = st.file_uploader("Reviews CSV", type="csv")
    st.caption("Columns: review_id, date, platform, rating, review_text")
    prev_file = st.file_uploader("Previous week's enriched CSV (optional)", type="csv",
                                 help="For trend arrows. If left empty, the app compares with the most recent "
                                      "week it analysed before (saved in the 'history' folder).")
    concurrency = st.slider("Parallel requests", 1, 10, 5)  # how many reviews are sent to the AI at once
    # The button stays greyed-out until a file has been chosen.
    run = st.button("Analyse reviews", type="primary", disabled=file is None)

# ---------------------------------------------------------------------------
# WHEN THE BUTTON IS CLICKED: validate -> classify -> report.
# ---------------------------------------------------------------------------
if run and file is not None:
    # Step 1: read the CSV and check/clean it. Show a friendly error instead of a crash.
    try:
        raw = pd.read_csv(file, encoding="utf-8-sig")
        df, info = validate_csv(raw)
    except (CSVValidationError, pd.errors.ParserError, UnicodeDecodeError) as e:
        st.error(f"Could not read the file: {e}")
        st.stop()  # stop drawing the page here
    st.info(f"Validated: kept {info['rows_kept']} of {info['rows_in']} rows "
            f"({info['dropped']} dropped, {info['duplicates']} duplicate ids).")

    # Connect to the AI. If the API key is missing, tell the user what to do.
    try:
        review_chain, report_chain = build_review_chain(), build_report_chain()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    # Optional: last week's numbers from an uploaded enriched CSV (for the trend arrows).
    prev_stats = None
    if prev_file is not None:
        try:
            prev_stats = stats_from_enriched_csv(pd.read_csv(prev_file, encoding="utf-8-sig"))
        except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as e:
            st.warning(f"Previous-week file ignored: {e}")

    # Steps 2-3: tag every review, count, write the report, compare with last week (see weekly.py).
    bar = st.progress(0.0, text="Classifying reviews...")
    result = run_analysis(
        df, review_chain, report_chain, prev_stats=prev_stats, concurrency=concurrency,
        on_progress=lambda done, total: bar.progress(min(done / total, 1.0), text=f"Classified {done}/{total}"),
    )
    bar.empty()  # remove the progress bar
    st.session_state["report"] = result["report"]
    st.session_state["trend"] = result["trend"]
    st.session_state["df"] = result["enriched"]  # remember the results for the rest of the session

# If nothing has been analysed yet, show instructions and stop drawing the page.
if "df" not in st.session_state:
    st.write("Upload a CSV in the sidebar and click **Analyse reviews**. "
             "A sample file is in `sample_data/reviews_week40.csv`.")
    st.stop()

df: pd.DataFrame = st.session_state["df"]
tab_dash, tab_report, tab_table = st.tabs(["Dashboard", "Weekly report", "Reviews table"])

# ---------------------------------------------------------------------------
# TAB 1 - DASHBOARD: headline numbers, two charts, and the HIGH-urgency filter.
# ---------------------------------------------------------------------------
with tab_dash:
    only_high = st.toggle("Show only HIGH urgency reviews", value=False)   # the filter switch
    view = df[df["urgency"] == "high"] if only_high else df                # keep only HIGH rows if switched on
    ok = view[view["sentiment"] != NEEDS_REVIEW]                           # charts ignore failed reviews

    # Four headline numbers across the top.
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reviews shown", len(view))  # (trend arrows below compare with the previous week)
    trend = st.session_state.get("trend")  # None when there is no earlier week to compare with
    # Arrows compare WHOLE weeks, so they are hidden while the HIGH filter narrows the table.
    show_trend = trend is not None and not only_high
    c2.metric("High urgency", int((df["urgency"] == "high").sum()),
              delta=trend["high_urgency"] if show_trend else None, delta_color="inverse")
    c3.metric("Negative", f"{(ok['sentiment'] == 'negative').mean() * 100:.0f}%" if len(ok) else "-",
              delta=f"{trend['negative_pct']:+g} pts" if show_trend else None, delta_color="inverse")
    c4.metric("Needs review", int((df["sentiment"] == NEEDS_REVIEW).sum()))

    if trend is not None:
        st.caption(f"Arrows compare with the previous period "
                   f"({trend['prev_from']:%d %b} to {trend['prev_to']:%d %b %Y}).")
    left, right = st.columns(2)
    colors = {"positive": "#2e9e5b", "neutral": "#9aa0a6", "negative": "#d9534f"}  # green / grey / red
    with left:  # donut chart: share of each sentiment
        s = ok["sentiment"].value_counts().reset_index()
        s.columns = ["sentiment", "count"]
        st.plotly_chart(px.pie(s, names="sentiment", values="count", hole=0.45, title="Sentiment split",
                               color="sentiment", color_discrete_map=colors), use_container_width=True)
    with right:  # bar chart: reviews per category, coloured by sentiment
        cat = ok.groupby(["category", "sentiment"]).size().reset_index(name="count")
        st.plotly_chart(px.bar(cat, x="category", y="count", color="sentiment", title="Reviews by category",
                               color_discrete_map=colors), use_container_width=True)

    # The table beneath the charts, including the ready-to-post suggested reply.
    st.subheader("High urgency - reply today" if only_high else "Reviews")
    show = view[["review_id", "date", "platform", "rating", "urgency", "category", "summary", "suggested_reply"]]
    st.dataframe(show, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# TAB 2 - WEEKLY REPORT: the text report plus a download button.
# ---------------------------------------------------------------------------
with tab_report:
    st.code(st.session_state.get("report", ""), language=None)
    st.download_button("Download report (.txt)", st.session_state.get("report", ""), "weekly_report.txt")

# ---------------------------------------------------------------------------
# TAB 3 - FULL TABLE and the Excel-ready CSV download.
# ---------------------------------------------------------------------------
with tab_table:
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button("Download enriched CSV (Excel-ready)", to_excel_csv(df), "reviews_enriched.csv", "text/csv")
