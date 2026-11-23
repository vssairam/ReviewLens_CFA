"""
send_weekly_report.py  -  "The Monday-morning robot"

WHAT THIS FILE DOES (in plain words)
------------------------------------
Runs the whole ReviewLens job WITHOUT the web page and e-mails the weekly report:

   find the newest CSV in the  inbox/  folder  ->  validate  ->  classify  ->  report
   ->  compare with last week  ->  e-mail it (report in the body, tagged CSV attached)

Put each week's reviews CSV into  inbox/  and let Windows Task Scheduler run this every Monday
(setup steps are in README.md).

Usage:
    python send_weekly_report.py                  # newest CSV in inbox/, sends the e-mail
    python send_weekly_report.py --csv path.csv   # use a specific file
    python send_weekly_report.py --dry-run        # do everything but save the e-mail to outbox/ instead of sending
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")  # works no matter which folder Task Scheduler starts the script in

import pandas as pd  # noqa: E402  (imported after load_dotenv so settings are ready)

from reviewlens.chains import build_report_chain, build_review_chain  # noqa: E402
from reviewlens.pipeline import CSVValidationError, validate_csv  # noqa: E402
from reviewlens.weekly import build_email, run_analysis, send_email, smtp_settings  # noqa: E402


def newest_csv(folder: Path) -> Path:
    files = sorted(folder.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No .csv file found in {folder}. Drop this week's reviews there.")
    return files[0]


def main() -> int:
    # Windows consoles often use a legacy encoding that cannot print the trend arrows or Tamil text.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Analyse a week of reviews and e-mail the report.")
    ap.add_argument("--csv", type=Path, help="reviews file (default: newest .csv in inbox/)")
    ap.add_argument("--dry-run", action="store_true", help="save the e-mail to outbox/ instead of sending it")
    args = ap.parse_args()

    try:
        path = args.csv or newest_csv(HERE / "inbox")
        print(f"Reading {path}")
        df, info = validate_csv(pd.read_csv(path, encoding="utf-8-sig"))
        print(f"Validated: kept {info['rows_kept']} of {info['rows_in']} rows")
        cfg = None if args.dry_run else smtp_settings()  # fail early, BEFORE spending money on the AI
        result = run_analysis(df, build_review_chain(), build_report_chain(),
                              on_progress=lambda d, t: print(f"  classified {d}/{t}"))
    except (FileNotFoundError, CSVValidationError, RuntimeError, pd.errors.ParserError, UnicodeDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if result["error"]:
        print(f"ERROR: the report step failed: {result['error']}", file=sys.stderr)
        return 1

    if args.dry_run:
        out = HERE / "outbox"
        out.mkdir(exist_ok=True)
        msg = build_email(result, "reviewlens@example.com", ["manager@example.com"])
        (out / "weekly_report.txt").write_text(result["report"], encoding="utf-8")
        (out / "weekly_email.eml").write_bytes(bytes(msg))
        print(f"\nDRY RUN - nothing sent. Files saved in {out}\n\n{result['report']}")
        return 0

    send_email(build_email(result, cfg["sender"], cfg["to"]), cfg)
    print(f"E-mail sent to {', '.join(cfg['to'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
