"""Apply manual DUV corrections."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "grandmasters.db"
CACHE = ROOT / "data" / "duv_matches.json"

# (name substring match, duv_id, duv_display_name)
FIXES = [
    ("Ellen Yin Kwan Cheng", "606145", "Cheng, Ellen Yin Kwan"),
    ("Patrick Cheung", "908142", "Cheung, Patrick"),
]


def main() -> None:
    conn = sqlite3.connect(DB, timeout=60)
    conn.row_factory = sqlite3.Row
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    for name_q, duv, duv_name in FIXES:
        rows = conn.execute(
            "SELECT id, name, country FROM runners WHERE name LIKE ? COLLATE NOCASE",
            (f"%{name_q}%",),
        ).fetchall()
        if not rows:
            print("NOT FOUND", name_q)
            continue
        if len(rows) > 1:
            # prefer exact-ish
            exact = [r for r in rows if name_q.lower() in r["name"].lower()]
            rows = exact or rows
        for r in rows:
            url = f"https://statistik.d-u-v.org/getresultperson.php?runner={duv}"
            conn.execute(
                """
                UPDATE runners
                SET duv_runner_id=?, duv_url=?, duv_match_status=?, duv_match_score=?, duv_name=?
                WHERE id=?
                """,
                (duv, url, "manual", 999, duv_name, r["id"]),
            )
            key = str(r["id"])
            cache[key] = {
                **(cache.get(key) or {}),
                "atm_name": r["name"],
                "duv_runner_id": duv,
                "duv_url": url,
                "duv_name": duv_name,
                "status": "manual",
                "score": 999,
            }
            print("updated", r["id"], r["name"], "->", duv)

    conn.commit()
    CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    for name_q, duv, _ in FIXES:
        for r in conn.execute(
            "SELECT id, name, duv_runner_id, duv_url, duv_match_status FROM runners WHERE name LIKE ? COLLATE NOCASE",
            (f"%{name_q}%",),
        ):
            print(tuple(r))
    conn.close()


if __name__ == "__main__":
    main()
