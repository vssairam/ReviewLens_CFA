# ReviewLens - Customer Feedback Analyzer

> **Solution guide with diagrams:** [`ARTEFACTS.html`](ARTEFACTS.html). When GitHub Pages is on, it is published at
> https://vssairam.github.io/ReviewLens_CFA/

Upload a week of reviews (English / Tamil / Tanglish) and get tagged reviews, a dashboard,
a weekly report with week-over-week trend arrows, and an Excel-ready CSV. The report can also be e-mailed
automatically every Monday.

## Setup
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then put your OPENAI_API_KEY in .env
streamlit run app.py
```
Try it with `sample_data/reviews_week40.csv` (240 rows incl. Tamil/Tanglish and a few deliberately bad rows).
Regenerate it with `python sample_data/generate_sample.py`.

## How it works
1. **Validate** (`pipeline.validate_csv`): checks columns, drops empty/duplicate/bad-date rows.
2. **Classify** (`chains.build_review_chain`): `ChatPromptTemplate | llm.with_structured_output(ReviewAnalysis)`,
   run with `chain.batch(max_concurrency=N)`. Invalid or failed outputs are retried automatically
   (`REVIEWLENS_MAX_RETRIES`), then marked `needs review`.
3. **Aggregate** (`analytics.compute_stats`): all counts and percentages are computed in pandas.
4. **Report** (`chains.build_report_chain`): the LLM sees the stats + review summaries and writes themes and
   3 action items; the counts shown beside each theme are filled in from pandas, never from the LLM.
5. **Show + export**: Streamlit dashboard with a HIGH-urgency filter; CSV is UTF-8 with BOM so Tamil opens correctly in Excel.

## Stretch goals (all three built)
1. **Trend vs last week.** Each analysed week's numbers are saved in `history/`. The next run compares with the most
   recent earlier week and shows arrows (▲ ▼ ►, marked better/worse) in the report and on the dashboard. Or upload
   last week's *enriched CSV* in the sidebar. Try it: `python sample_data/generate_sample.py 39` makes a milder
   earlier week; analyse `reviews_week39.csv` first, then `reviews_week40.csv`.
2. **Replies in the customer's language.** English -> English, Tamil script -> Tamil, Tanglish -> Tanglish.
   Summaries stay in English. Set `REVIEWLENS_REPLY_LANGUAGE=english` to switch it off.
3. **Monday e-mail.** `send_weekly_report.py` analyses the newest CSV in `inbox/` and e-mails the report
   (CSV attached). Fill the `SMTP_*` / `REPORT_TO` lines in `.env`, then test without sending:
   ```powershell
   python send_weekly_report.py --dry-run          # saves the e-mail to outbox/ instead of sending
   python send_weekly_report.py                    # really sends
   ```
   Schedule it for every Monday 9:00 (Windows Task Scheduler; adjust the folder):
   ```powershell
   schtasks /Create /SC WEEKLY /D MON /ST 09:00 /TN "ReviewLens Weekly Report" /TR "\"D:\path\to\ReviewLens_CFA\.venv\Scripts\python.exe\" \"D:\path\to\ReviewLens_CFA\send_weekly_report.py\""
   ```
   The PC must be on at that time (or use "run as soon as possible after a missed start" in Task Scheduler).

## Configuration (`.env`)
| Variable | Default |
|---|---|
| `REVIEWLENS_PROVIDER` | `openai` (or `anthropic`) |
| `OPENAI_API_KEY` | required when provider is `openai` |
| `ANTHROPIC_API_KEY` | required only when provider is `anthropic` |
| `REVIEWLENS_MODEL` | `gpt-4o-mini` (per-review) |
| `REVIEWLENS_REPORT_MODEL` | `gpt-4o` (weekly report) |
| `REVIEWLENS_MAX_CONCURRENCY` | 5 |
| `REVIEWLENS_MAX_RETRIES` | 2 |
| `REVIEWLENS_REPLY_LANGUAGE` | `same` (or `english`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `REPORT_FROM`, `REPORT_TO` | only for the Monday e-mail |

Only `get_llm()` in `reviewlens/chains.py` knows the AI provider.

Full explanation of every program with diagrams: `docs/ReviewLens_Program_Guide.md`.

## Tests
`python -m pytest -q` (uses a stub chain; no API key or network needed).
