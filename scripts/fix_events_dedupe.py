"""Re-dedupe existing events.json / SQLite without re-scraping."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from scrape_events import (  # noqa: E402
    DB_PATH,
    OUT_JSON,
    dedupe_events,
    ensure_schema,
    log,
)


def main() -> None:
    raw = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    # Clear prior season-guess annotations before re-deriving dates
    for e in raw:
        label = e.get("date_label") or ""
        e["date_label"] = re.sub(r"\s*\(~S\d+\s*→\s*\d{4}\)$", "", label).strip()
        if not e.get("date_start") or re.search(r"→\s*\d{4}\)$", label):
            # allow refill for previously guessed rows if date_start came only from guess
            pass
    unique = dedupe_events(raw)
    log(f"deduped {len(raw)} -> {len(unique)}")
    filled = sum(1 for e in unique if e.get("date_start") and "(~S" in (e.get("date_label") or ""))
    missing = sum(1 for e in unique if not e.get("date_start"))
    log(f"season-guessed years={filled} still_missing_date={missing}")
    OUT_JSON.write_text(json.dumps(unique, indent=2, ensure_ascii=False), encoding="utf-8")

    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_schema(conn)
    conn.execute("DELETE FROM events")
    for e in unique:
        conn.execute(
            """
            INSERT INTO events (
              season, calendar, name, country, country_code, region,
              date_label, date_start, distances, notes, status,
              championship, grandmaster, is_final, is_gm_only,
              announcement_url, report_url, results_url, source_url, raw
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                e["season"],
                e["calendar"],
                e["name"],
                e["country"],
                e["country_code"],
                e["region"],
                e["date_label"],
                e["date_start"],
                e["distances"],
                e["notes"],
                e["status"],
                e["championship"],
                e["grandmaster"],
                e["is_final"],
                e["is_gm_only"],
                e.get("announcement_url") or "",
                e.get("report_url") or "",
                e.get("results_url") or "",
                e["source_url"],
                e.get("raw") or "",
            ),
        )
    conn.commit()
    # verify Izu / Apo
    for name in ("Izu Trail Journey: 70 km", "Mount Apo Sky Race: 100 km"):
        rows = conn.execute(
            "SELECT season, calendar, date_label FROM events WHERE name=? ORDER BY season",
            (name,),
        ).fetchall()
        log(f"  {name}: {rows}")
    dups = conn.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT 1 FROM events
          GROUP BY lower(replace(name,' ','')), coalesce(date_start,''), coalesce(date_label,''),
                   coalesce(country_code,''), calendar
          HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    by = conn.execute(
        "SELECT season, calendar, COUNT(*) FROM events GROUP BY 1,2 ORDER BY 1 DESC, 2"
    ).fetchall()
    log(f"remaining exact dups={dups} counts={by}")
    conn.close()


if __name__ == "__main__":
    main()
