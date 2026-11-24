import sqlite3
from pathlib import Path

c = sqlite3.connect(Path(r"c:\Users\user\src\trail\data\grandmasters.db"))
cols = [r[1] for r in c.execute("PRAGMA table_info(runners)")]
print("cols", cols)
for col in ["rts_url", "duv_url", "rts_match_status", "duv_match_status"]:
    if col in cols:
        n = c.execute(
            f"SELECT COUNT(*) FROM runners WHERE {col} IS NOT NULL AND {col} != ''"
        ).fetchone()[0]
        print(col, n)
    else:
        print(col, "MISSING")
if "rts_match_status" in cols:
    rows = c.execute(
        "SELECT rts_match_status, COUNT(*) FROM runners GROUP BY rts_match_status"
    ).fetchall()
    print("rts status", rows)
