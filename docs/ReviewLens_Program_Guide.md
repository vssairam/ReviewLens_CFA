# ReviewLens - Program Guide

*A plain-language explanation of every program in the project, with diagrams.*
*(Diagrams use Mermaid and render automatically on GitHub, VS Code (Markdown Preview Mermaid extension) and most Markdown viewers.)*

---

## 1. The problem in one paragraph

A restaurant chain or online store gets 200-500 reviews a week from Google, Zomato, Swiggy and Amazon, in English, Tamil and Tanglish (Tamil typed in English letters). A manager reading them by hand misses urgent complaints (food poisoning, wrong order, rude staff) and cannot say with numbers what customers complain about most. **ReviewLens** reads every review with an AI, tags it, counts everything, writes a one-page weekly report and shows a dashboard, so the manager can act in five minutes.

## 2. The big picture

```mermaid
flowchart LR
    A[1. Upload CSV<br/>of reviews] --> B[2. Validate<br/>check and clean]
    B --> C[3. Classify<br/>AI tags each review]
    C --> D[4. Aggregate<br/>pandas counts]
    D --> E[5. Report<br/>AI writes insights]
    E --> F[6. Dashboard<br/>and CSV download]
    C --> F
```

Think of it as a **factory line**: raw reviews go in at the left, a finished manager's report and a tidy spreadsheet come out at the right. Each station is one part of the code.

## 3. Project layout - what each file is

```text
ReviewLens_CFA/
├── app.py                      <- the web page (what the manager sees)
├── reviewlens/
│   ├── schema.py               <- the rulebook: allowed values and answer forms
│   ├── chains.py               <- instructions to the AI + connection to OpenAI/Claude
│   ├── pipeline.py             <- cleans the CSV, runs the AI on every review, retries
│   └── analytics.py            <- counts with pandas, writes the weekly report
├── sample_data/
│   ├── generate_sample.py      <- makes the practice CSV
│   └── reviews_week40.csv      <- 240 practice reviews (English / Tamil / Tanglish)
├── tests/test_pipeline.py      <- automatic safety checks
├── requirements.txt            <- list of libraries to install
├── .env.example                <- template for the secret API key file
└── README.md                   <- quick start
```

### How the files depend on each other

```mermaid
flowchart TD
    app[app.py<br/>web page] --> pipeline[pipeline.py<br/>clean + run AI]
    app --> analytics[analytics.py<br/>counts + report]
    app --> chains[chains.py<br/>AI instructions]
    pipeline --> schema[schema.py<br/>rulebook]
    analytics --> schema
    chains --> schema
    chains -->|OPENAI_API_KEY| env[(.env file<br/>secret key)]
    tests[test_pipeline.py] -.tests.-> pipeline
    tests -.tests.-> analytics
```

An arrow means "uses". `schema.py` is at the bottom because everyone shares its rules, and it uses nobody.

---

## 4. Program-by-program explanation

### 4.1 `reviewlens/schema.py` - "The rulebook"

**Purpose:** decide in advance exactly what an AI answer must look like, so the AI cannot return free-form text.

**Analogy:** a form with fixed boxes. For *sentiment* you may tick only *positive*, *neutral* or *negative*; you cannot write "kinda bad".

| Item | What it is |
|---|---|
| `Sentiment`, `Category`, `Urgency`, `Language` | The allowed words for each box |
| `REQUIRED_COLUMNS` | The 5 columns every uploaded CSV must have |
| `NEEDS_REVIEW` | The label for "the AI failed, a human must read this" |
| `ReviewAnalysis` | The form for **one review** (6 boxes) |
| `ThemeItem`, `WeeklyInsights` | The form for the **weekly report** (themes + 3 action items) |

```mermaid
classDiagram
    class ReviewAnalysis {
      sentiment : positive | neutral | negative
      category : food_quality | delivery | price | staff | packaging | app
      urgency : low | medium | high
      language : English | Tamil | Tanglish | Other
      summary : one English sentence
      suggested_reply : polite reply
    }
    class WeeklyInsights {
      top_complaints : list of ThemeItem
      top_praises : list of ThemeItem
      action_items : 3 strings
    }
    class ThemeItem {
      category
      theme
      detail
    }
    WeeklyInsights --> ThemeItem
```

Note that `WeeklyInsights` has **no number fields** on purpose: the AI is never asked to count.

### 4.2 `reviewlens/chains.py` - "The instructions and the AI connection"

**Purpose:** build the two "assembly lines" (LangChain *chains*) that talk to the AI.

**A chain** is written with the `|` symbol and works like a conveyor belt:

```mermaid
flowchart LR
    I[Review details<br/>platform, rating, text] --> P[Prompt template<br/>fills in the blanks]
    P --> M[AI model<br/>OpenAI gpt-4o-mini]
    M --> S[Structured output<br/>forced into ReviewAnalysis]
    S --> R[Typed result]
```

| Piece | Plain meaning |
|---|---|
| `REVIEW_SYSTEM` | The standing rules for the per-review AI: understand Tamil/Tanglish, pick from allowed lists, always summarise in English, ignore instructions hidden inside a review |
| `REVIEW_HUMAN` | The template for the actual review, with blanks `{platform}`, `{rating}`, `{review_text}` |
| `REPORT_SYSTEM` / `REPORT_HUMAN` | Same idea for the weekly-report AI |
| `get_llm()` | **The only place that knows which AI company is used.** Reads `REVIEWLENS_PROVIDER` (`openai` default, or `anthropic`), checks the API key exists, and creates the connection. `temperature=0` makes answers consistent |
| `build_review_chain()` | prompt `|` AI `|` forced structure (`ReviewAnalysis`) |
| `build_report_chain()` | same, with a stronger model, forced structure `WeeklyInsights` |

**Swapping the AI:** set `REVIEWLENS_PROVIDER=anthropic` in `.env`. Nothing else changes - this is the "swap models without changing the chain" requirement.

### 4.3 `reviewlens/pipeline.py` - "The factory floor"

**Purpose:** clean the spreadsheet, run the AI over every review, handle failures, and produce the download file.

#### `validate_csv` - the quality gate

```mermaid
flowchart TD
    A[Uploaded table] --> B{All 5 required<br/>columns present?}
    B -- No --> X[Stop with a clear error message]
    B -- Yes --> C[Drop rows with empty review text]
    C --> D[Drop rows with no review_id,<br/>drop duplicate ids]
    D --> E[Convert date and rating;<br/>drop rows with unreadable date]
    E --> F{Any rows left?}
    F -- No --> X
    F -- Yes --> G[Clean table + counts of what was dropped]
```

#### `analyze_reviews` - classify with automatic retry

The AI sometimes fails (network blip, invalid category). Rather than lose a review, the program asks again, and only after all retries fail does it mark the review `needs review`.

```mermaid
flowchart TD
    S[All reviews are 'pending'] --> R{Attempt number<br/>0 to max_retries}
    R --> B[Send pending reviews in groups of 25<br/>chain.batch, max_concurrency at a time]
    B --> V{Is each answer<br/>valid?}
    V -- Yes --> OK[Store the answer]
    V -- No --> BAD[Stay pending for next round]
    BAD --> R
    OK --> D{Any pending left?}
    D -- Yes, retries remain --> R
    D -- No --> F[Done]
    D -- Yes, retries used up --> N[Mark 'needs review'] --> F
```

"Valid" (`_is_valid`) means: a proper `ReviewAnalysis`, every constrained value on its allowed list, and a non-blank summary and reply.

`chain.batch(..., max_concurrency=5)` sends up to 5 reviews at the same time. That is much faster than one at a time, but stays under the AI company's rate limits. `return_exceptions=True` means one failed review never crashes the whole run.

#### `to_excel_csv`
Produces the download file with a hidden "BOM" marker (`utf-8-sig`) so that Excel shows Tamil letters correctly instead of garbage.

### 4.4 `reviewlens/analytics.py` - "The calculator and report writer"

**Purpose:** the **reduce** step. Hundreds of per-review results become one report.

**Map then reduce:** the *map* step handles each review separately (cheap, parallel). The *reduce* step squeezes all results into one short report. This is how you summarise data that is too big to paste into a single AI prompt.

```mermaid
flowchart LR
    T[Tagged table<br/>248 rows] --> CS[compute_stats<br/>pandas counts]
    T --> SUM[_summaries<br/>one line per review,<br/>urgent first, max 300]
    CS --> TXT[_stats_text]
    TXT --> AI[Report AI]
    SUM --> AI
    AI --> INS[Themes + 3 action items<br/>WeeklyInsights]
    CS --> REP[render_report]
    INS --> REP
    REP --> OUT[Final text report]
```

**The key design rule:** *numbers come from pandas, wording comes from the AI.* In `render_report`, the figure beside each complaint theme is the pandas count of negative reviews in that theme's category. Language models are poor at counting, so the AI is never trusted with arithmetic. That is why the report always matches the table exactly.

### 4.5 `app.py` - "The screen the manager sees"

**Purpose:** the Streamlit web page. Streamlit re-runs the file from top to bottom on every click, so results are saved in `st.session_state` (the page's memory).

```mermaid
sequenceDiagram
    actor M as Manager
    participant UI as app.py (Streamlit)
    participant P as pipeline.py
    participant AI as OpenAI API
    participant A as analytics.py
    M->>UI: Upload CSV, click "Analyse reviews"
    UI->>P: validate_csv(table)
    P-->>UI: clean table (or friendly error)
    UI->>P: analyze_reviews(table, review chain)
    loop each group of 25 reviews
        P->>AI: classify reviews (parallel)
        AI-->>P: structured answers
        P-->>UI: progress update
    end
    P-->>UI: table with 6 new columns
    UI->>A: generate_insights(table, report chain)
    A->>AI: stats + summaries
    AI-->>A: themes and action items
    A-->>UI: report text
    UI-->>M: Dashboard, report, table, CSV download
```

**What the manager sees**

```text
+-----------------------------------------------------------------+
| ReviewLens                                                      |
+-----------+-----------------------------------------------------+
| Upload    | [Dashboard] [Weekly report] [Reviews table]         |
| [file...] |  [x] Show only HIGH urgency reviews                 |
| slider    |  Reviews | High urgency | Negative % | Needs review |
| [Analyse] |  (donut: sentiment split)  (bars: by category)      |
|           |  table: id | date | urgency | summary | reply      |
+-----------+-----------------------------------------------------+
```

* **Dashboard tab:** four headline numbers, a donut chart (sentiment split), a bar chart (category, coloured by sentiment) and the **HIGH-urgency toggle**, which filters every number, chart and table at once.
* **Weekly report tab:** the text report and a download button.
* **Reviews table tab:** the full enriched table and the **Excel-ready CSV** download.

### 4.6 `sample_data/generate_sample.py`
Creates `reviews_week40.csv` with 240 practice rows in English, Tamil and Tanglish, plus 4 deliberately broken rows (blank text, spaces only, duplicate id, invalid date) to prove validation works. A fixed random seed makes the file identical on every run.

### 4.7 `tests/test_pipeline.py`
Five automatic checks that use a **fake AI** (so no API key, no cost, same result every time):

| Test | What it proves |
|---|---|
| `test_validate_drops_empty_and_duplicates` | Blank and repeated rows are removed |
| `test_validate_missing_column` | A file without a required column is rejected |
| `test_retry_then_success_and_needs_review` | A failing review is retried; a hopeless one becomes `needs review` after all retries |
| `test_stats_and_report_numbers_from_pandas` | Percentages and report counts come from pandas |
| `test_csv_export_has_bom` | The download file is Excel-safe |

---

## 5. One review, end to end (worked example)

Input row: `R-1042, 2026-10-03, Swiggy, 1, "Ordered at 8pm, came at 9:10. Food fully cold. Very bad."`

1. **Validate:** all columns present, text not empty, id unique, date readable -> kept.
2. **Classify:** the chain fills the template with *Swiggy / 1 / the text* and the AI returns:
   `sentiment=negative, category=delivery, urgency=high, language=English, summary="Order arrived 70 minutes late and the food was cold.", suggested_reply="We are really sorry..."`
3. **Check:** every value is on the allowed list -> accepted. (If not, it is asked again up to 2 more times.)
4. **Aggregate:** it adds +1 to *negative*, *delivery*, *Swiggy*, *high urgency* in the pandas counts.
5. **Report:** the AI sees "delivery | Swiggy | Order arrived 70 minutes late..." among the negatives and may name the theme "Late delivery"; the number next to it is the pandas count.
6. **Show:** the review appears in the table; switching on *HIGH urgency* keeps it; the CSV download includes all 6 new columns.

## 6. How the "Done checklist" is satisfied

| Requirement | Where it is met |
|---|---|
| Processes 200+ rows without crashing/timeouts | Batches of 25, `max_concurrency`, per-call 60 s timeout, `return_exceptions=True` (`pipeline.py`, `chains.py`) |
| Every review has all 6 fields from the allowed list | Pydantic `Literal` types + `_is_valid` + retry + `needs review` fallback |
| Tamil / Tanglish get an English summary | Instructions in `REVIEW_SYSTEM`; sample data contains both |
| Report numbers match the table | All counts from pandas (`compute_stats`); AI never counts |
| HIGH urgency filter + Excel-ready CSV | Dashboard toggle; `to_excel_csv` with BOM |
| API key from `.env`, never hard-coded | `load_dotenv()` + `os.getenv(...)`; `.env` is in `.gitignore` |

## 7. Glossary (for non-programmers)

| Term | Meaning |
|---|---|
| **LLM** | The AI language model (here OpenAI's GPT, or Anthropic's Claude) |
| **Prompt** | The written instructions given to the AI |
| **Chain (LCEL)** | Steps joined with `\|`, output of one feeding the next |
| **Structured output** | Forcing the AI to answer in a fixed form, not free text |
| **Pydantic** | The library that defines the form and rejects wrong values |
| **Batch / concurrency** | Sending many items together / several at the same moment |
| **Map then reduce** | Process items one by one, then combine into one summary |
| **pandas / DataFrame** | Python's spreadsheet-like table tools |
| **Streamlit** | Turns a Python file into a web page |
| **Tanglish** | Tamil written in English letters |
| **BOM** | Invisible marker that makes Excel read Tamil text correctly |
| **.env file** | A private file holding the secret API key |
