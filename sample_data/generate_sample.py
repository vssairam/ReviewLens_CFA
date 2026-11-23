"""
generate_sample.py  -  "Makes practice data"

WHAT THIS FILE DOES (in plain words)
------------------------------------
Creates a fake-but-realistic spreadsheet (reviews_week40.csv) of 240 customer reviews so the
app can be tried without real customer data. It mixes English, Tamil and Tanglish reviews,
good and bad experiences, and a few deliberately BROKEN rows (blank text, a duplicate id, an
invalid date) to prove that the app's validation step catches them.

Run:  python sample_data/generate_sample.py
The random seed below is fixed, so every run produces the identical file.
"""
import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

WEEK = int(sys.argv[1]) if len(sys.argv) > 1 else 40  # optional: 'python generate_sample.py 39' = the week before
random.seed(WEEK)  # fixed seed = same "random" choices every time (repeatable results)

# Each entry is (review text, star rating). Lists are grouped by language.
EN = [  # English reviews
    ("Biryani was amazing, packing also neat. Will order again!", 5), ("Loved the butter chicken, perfect spice.", 5),
    ("Ordered at 8pm, came at 9:10. Food fully cold. Very bad.", 1), ("Delivery took over an hour and the food was cold.", 1),
    ("Got food poisoning after eating the chicken rice. Vomiting all night.", 1),
    ("Wrong order delivered, I asked for veg and got non-veg. Want a refund.", 1),
    ("The waiter was very rude and shouted at us.", 1), ("Portion size is too small for the price.", 2),
    ("Too expensive compared to other places.", 2), ("Packaging was leaking, gravy spilled everywhere.", 2),
    ("App keeps crashing when I try to pay.", 2), ("Staff were friendly and helpful.", 5),
    ("Food was okay, nothing special.", 3), ("Good taste but delivery was a bit slow.", 3),
    ("Charged extra packing and service charge that was not on the menu.", 2), ("Great value combo, very filling.", 4),
]
TA = [  # Tamil-script reviews
    ("பிரியாணி மிகவும் சுவையாக இருந்தது, மீண்டும் ஆர்டர் செய்வேன்.", 5),
    ("டெலிவரி ரொம்ப தாமதம், சாப்பாடு குளிர்ந்து போச்சு.", 1),
    ("சாப்பிட்ட பிறகு வயிற்று வலி வந்தது, உணவு சரியில்லை.", 1),
    ("ஊழியர்கள் மரியாதையாக நடந்து கொண்டனர்.", 4), ("விலை மிக அதிகம், அளவு குறைவு.", 2),
]
TG = [  # Tanglish reviews (Tamil written in English letters)
    ("Saapadu nalla irundhuchu but bill la extra charge pottanga", 2),
    ("Biryani semma taste, packing um super. Kandippa thirumba order panven!", 5),
    ("Delivery romba late, food thanda aagi pochu. Waste.", 1),
    ("Waiter romba rude ah pesinaanga, mariyadhai illa.", 1),
    ("Saapadu sapta aprm vayiru valikuthu, food poisoning maari irukku.", 1),
    ("Rate romba jaasthi, quantity korachal.", 2), ("Service okay, taste average dhaan.", 3),
    ("Order maathi kuduthutaanga, veg ku badhila non-veg vandhuchu.", 1),
    ("App la payment fail aaitu, but money cut aayiduchu.", 1), ("Super taste, staff um nalla pesuvanga.", 5),
]
PLATFORMS = ["Google", "Zomato", "Swiggy", "Amazon"]

# Repeat each list several times (so we reach ~236 rows) and shuffle so languages are mixed up.
pool = [(t, r, "en") for t, r in EN] * 9 + [(t, r, "ta") for t, r in TA] * 5 + [(t, r, "tg") for t, r in TG] * 7
random.shuffle(pool)

start = date(2026, 10, 3) - timedelta(weeks=40 - WEEK)  # first day of the sample week
rows = []
if WEEK < 40:
    # An earlier week that went BETTER than week 40: complaints (rating 1-2) are drawn only ~60% as often,
    # so the app's trend arrows have something real to show. (Week 40 itself is unchanged.)
    pool = random.choices(pool, weights=[0.6 if r <= 2 else 1.0 for _, r, _ in pool], k=236)
for i, (text, rating, _) in enumerate(pool[:236]):
    rows.append([
        f"R-{1041 - 200 * (40 - WEEK) + i}",                                                    # review id: R-1041, R-1042, ...
        (start + timedelta(days=random.randint(0, 6))).isoformat(),         # a random day within the week
        random.choice(PLATFORMS),                                           # a random platform
        rating,
        text,
    ])

# Deliberately messy rows to test validation: empty text, spaces-only text, repeated id, bad date.
rows += [["R-9001", start.isoformat(), "Google", 3, ""], ["R-9002", start.isoformat(), "Zomato", 4, "   "],
         [rows[0][0], start.isoformat(), "Swiggy", 5, "Duplicate id row"], ["R-9003", "not-a-date", "Google", 2, "Bad date row"]]

# Write the CSV. "utf-8-sig" lets Excel display the Tamil text correctly.
out = Path(__file__).parent / f"reviews_week{WEEK}.csv"
with out.open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["review_id", "date", "platform", "rating", "review_text"])  # header row
    w.writerows(rows)
print(f"Wrote {len(rows)} rows to {out}")
