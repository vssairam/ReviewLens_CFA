"""
schema.py  -  "The rulebook"

WHAT THIS FILE DOES (in plain words)
------------------------------------
Before the AI reads any review, we need to agree on exactly what kind of answer we want
back. Think of it like a form with fixed boxes: the AI must tick one option in each box
and cannot invent its own. This file defines those forms and the allowed options.

Two forms are defined here:
  1. ReviewAnalysis  - the filled-in form for ONE review (sentiment, category, ...)
  2. WeeklyInsights  - the filled-in form for the WHOLE WEEK's report (themes + actions)

We use a library called "Pydantic" to build these forms. If the AI ever returns a value
that is not on the allowed list, Pydantic rejects it - that is how we guarantee clean data.
"""
from typing import Literal, get_args

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# The allowed options for each box on the form.
# "Literal" simply means: the value MUST be exactly one of the words listed.
# ---------------------------------------------------------------------------
Sentiment = Literal["positive", "neutral", "negative"]          # overall mood of the customer
Category = Literal["food_quality", "delivery", "price", "staff", "packaging", "app"]  # which department is concerned
Urgency = Literal["low", "medium", "high"]                      # how fast we must reply
Language = Literal["English", "Tamil", "Tanglish", "Other"]     # Tanglish = Tamil typed in English letters

# The same lists, converted to ordinary Python lists so other files can loop over them
# (for example to check a value, or to draw a chart in a fixed order).
SENTIMENTS = list(get_args(Sentiment))
CATEGORIES = list(get_args(Category))
URGENCIES = list(get_args(Urgency))
LANGUAGES = list(get_args(Language))

# The five columns the uploaded CSV file must contain. If any is missing we stop with a clear message.
REQUIRED_COLUMNS = ["review_id", "date", "platform", "rating", "review_text"]

# Special label placed on a review when the AI could not give a valid answer even after retrying.
# It tells the manager: "a human should read this one."
NEEDS_REVIEW = "needs review"


class ReviewAnalysis(BaseModel):
    """The filled-in form for ONE review. Every box below is compulsory."""

    # 'Field(description=...)' is a hint that is also shown to the AI so it knows what each box means.
    sentiment: Sentiment = Field(description="Overall customer mood")
    category: Category = Field(description="Main department the feedback is about")
    urgency: Urgency = Field(
        description="high = reply today (health/food poisoning, refund, abuse, wrong order)"
    )
    language: Language = Field(description="Language of the review text")
    summary: str = Field(description="ONE sentence in English, even for Tamil/Tanglish")
    suggested_reply: str = Field(description="Polite, ready-to-post reply, 1-3 sentences")


class ThemeItem(BaseModel):
    """One 'theme' in the weekly report, e.g. 'Late delivery in the evenings'."""

    category: Category = Field(description="Category this theme belongs to")
    theme: str = Field(description="Short theme name, e.g. 'Late delivery in evenings'")
    detail: str = Field(description="One short line of context (platform, time, pattern)")


class WeeklyInsights(BaseModel):
    """The filled-in form for the whole week. NOTE: it deliberately has NO number fields -
    all counts are calculated by the program (pandas), never guessed by the AI."""

    top_complaints: list[ThemeItem] = Field(description="Up to 3 complaint themes, most important first")
    top_praises: list[ThemeItem] = Field(description="Up to 3 praise themes, most important first")
    action_items: list[str] = Field(description="Exactly 3 concrete, actionable items")
