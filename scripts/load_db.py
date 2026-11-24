"""Load grandmasters_full.json into SQLite."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = DATA / "grandmasters.db"
SOURCE = DATA / "grandmasters_full.json"

COUNTRY_NAMES = {
    "PHI": "Philippines",
    "MAS": "Malaysia",
    "BRU": "Brunei",
    "SGP": "Singapore",
    "INA": "Indonesia",
    "HKG": "Hong Kong",
    "IND": "India",
    "JPN": "Japan",
    "AUS": "Australia",
    "THA": "Thailand",
    "USA": "United States",
    "CAN": "Canada",
    "VIE": "Vietnam",
    "ITA": "Italy",
    "GBR": "United Kingdom",
    "NOR": "Norway",
    "KOR": "South Korea",
    "BEL": "Belgium",
}

FLAGS = {
    "PHI": "🇵🇭",
    "MAS": "🇲🇾",
    "BRU": "🇧🇳",
    "SGP": "🇸🇬",
    "INA": "🇮🇩",
    "HKG": "🇭🇰",
    "IND": "🇮🇳",
    "JPN": "🇯🇵",
    "AUS": "🇦🇺",
    "THA": "🇹🇭",
    "USA": "🇺🇸",
    "CAN": "🇨🇦",
    "VIE": "🇻🇳",
    "ITA": "🇮🇹",
    "GBR": "🇬🇧",
    "NOR": "🇳🇴",
    "KOR": "🇰🇷",
    "BEL": "🇧🇪",
}

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_grad_date(raw: str | None) -> str | None:
    if not raw:
        return None
    m = re.match(r"([A-Za-z]+)\s+(\d{4})", raw.strip())
    if not m:
        return None
    month = MONTHS.get(m.group(1).lower())
    if not month:
        return None
    return f"{m.group(2)}-{month:02d}-01"


def split_links(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split("|") if p.strip()]


def main() -> None:
    runners = json.loads(SOURCE.read_text(encoding="utf-8"))
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE runners (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          country TEXT NOT NULL,
          country_name TEXT,
          flag TEXT,
          gender TEXT,
          stars INTEGER NOT NULL,
          points INTEGER NOT NULL,
          last_race TEXT,
          graduated_label TEXT,
          graduated_on TEXT,
          profile_url TEXT,
          profile_heading TEXT,
          has_profile INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE links (
          id INTEGER PRIMARY KEY,
          runner_id INTEGER NOT NULL REFERENCES runners(id) ON DELETE CASCADE,
          label TEXT,
          url TEXT NOT NULL
        );
        CREATE TABLE races (
          id INTEGER PRIMARY KEY,
          runner_id INTEGER NOT NULL REFERENCES runners(id) ON DELETE CASCADE,
          raced_on TEXT,
          sort_key TEXT,
          label TEXT NOT NULL
        );
        CREATE INDEX idx_runners_name ON runners(name);
        CREATE INDEX idx_runners_country ON runners(country);
        CREATE INDEX idx_runners_stars ON runners(stars);
        CREATE INDEX idx_runners_points ON runners(points DESC);
        """
    )

    for i, r in enumerate(runners, start=1):
        profile = r.get("profile") or {}
        has_profile = 1 if profile else 0
        conn.execute(
            """
            INSERT INTO runners (
              id, name, country, country_name, flag, gender, stars, points,
              last_race, graduated_label, graduated_on, profile_url,
              profile_heading, has_profile
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                i,
                r["name"],
                r["country"],
                COUNTRY_NAMES.get(r["country"], r["country"]),
                FLAGS.get(r["country"], ""),
                r.get("gender"),
                int(r.get("stars") or 0),
                int(r.get("points") or 0),
                r.get("last") or None,
                r.get("date") or None,
                parse_grad_date(r.get("date")),
                profile.get("url"),
                profile.get("heading"),
                has_profile,
            ),
        )

        for idx, url in enumerate(split_links(r.get("link")), start=1):
            label = "Announcement" if idx == 1 else f"Announcement {idx}"
            if len(split_links(r.get("link"))) > 1 and idx == 1:
                label = "Announcement 1"
            conn.execute(
                "INSERT INTO links (runner_id, label, url) VALUES (?, ?, ?)",
                (i, label, url),
            )

        for race in profile.get("races") or []:
            m = re.match(r"^(\d{1,2})/(\d{4})\s*-\s*(.+)$", race.strip())
            if m:
                month, year, rest = m.group(1), m.group(2), m.group(3)
                raced_on = f"{year}-{int(month):02d}"
                sort_key = f"{year}-{int(month):02d}"
                label = f"{int(month):02d}/{year} - {rest}"
            else:
                raced_on = None
                sort_key = race
                label = race
            conn.execute(
                "INSERT INTO races (runner_id, raced_on, sort_key, label) VALUES (?, ?, ?, ?)",
                (i, raced_on, sort_key, label),
            )

    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM runners").fetchone()[0]
    p = conn.execute("SELECT COUNT(*) FROM runners WHERE has_profile=1").fetchone()[0]
    races = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    conn.close()
    print(f"loaded {n} runners, {p} with profiles, {races} races -> {DB_PATH}")


if __name__ == "__main__":
    main()
