"""Re-check verified_rts promotions; demote weak family-name mismatches back to guess."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

DB = Path(r"c:\Users\user\src\trail\data\grandmasters.db")


def tokens(name: str) -> set[str]:
    stop = {"bin", "binti", "van", "de", "da", "del", "jr", "ii", "iii"}
    return {
        t
        for t in re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
        if t and t not in stop and len(t) > 1
    }


def family_ok(atm: str, duv: str) -> bool:
    """DUV 'Surname, Given' — surname should appear in ATM name."""
    if not duv:
        return False
    if "," in duv:
        surname = duv.split(",", 1)[0]
    else:
        surname = duv.split()[-1] if duv.split() else ""
    s_toks = tokens(surname)
    a_toks = tokens(atm)
    if not s_toks:
        return False
    # all surname tokens in ATM, or ATM last token in surname tokens
    atm_parts = re.sub(r"[^a-z0-9]+", " ", atm.lower()).split()
    atm_last = atm_parts[-1] if atm_parts else ""
    if s_toks <= a_toks:
        return True
    if atm_last and atm_last in s_toks:
        return True
    # given-name nickname in parentheses on DUV shouldn't block
    return False


def main() -> None:
    conn = sqlite3.connect(DB, timeout=60)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, name, duv_name, duv_match_status
        FROM runners
        WHERE duv_match_status='verified_rts'
        """
    ).fetchall()
    demoted = 0
    kept = 0
    for r in rows:
        if family_ok(r["name"], r["duv_name"] or ""):
            kept += 1
            continue
        conn.execute(
            "UPDATE runners SET duv_match_status='guess' WHERE id=?",
            (r["id"],),
        )
        demoted += 1
        print(f"DEMOTE {r['name']} <- {r['duv_name']}")
    conn.commit()
    print(f"kept={kept} demoted={demoted}")

    # show AUS
    aus = conn.execute(
        "SELECT name, duv_match_status, duv_name FROM runners WHERE country='AUS'"
    ).fetchall()
    print("AUS:", [dict(r) for r in aus])
    print(
        "status",
        conn.execute(
            "SELECT duv_match_status, COUNT(*) FROM runners GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall(),
    )


if __name__ == "__main__":
    main()
