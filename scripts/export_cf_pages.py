"""Export a static Cloudflare Pages site from the local SQLite mock."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "grandmasters.db"
APP_STATIC = ROOT / "app" / "static"
DIST = ROOT / "cf-dist"


def row_to_runner(row: sqlite3.Row, links: list[dict], races: list[dict]) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "country": row["country"],
        "country_name": row["country_name"],
        "flag": row["flag"],
        "gender": row["gender"],
        "stars": row["stars"],
        "points": row["points"],
        "last_race": row["last_race"],
        "graduated_label": row["graduated_label"],
        "graduated_on": row["graduated_on"],
        "profile_url": row["profile_url"],
        "profile_heading": row["profile_heading"],
        "has_profile": bool(row["has_profile"]),
        "rts_runner_id": row["rts_runner_id"],
        "rts_url": row["rts_url"],
        "rts_match_status": row["rts_match_status"],
        "duv_runner_id": row["duv_runner_id"],
        "duv_url": row["duv_url"],
        "duv_match_status": row["duv_match_status"],
        "links": links,
        "races": races,
        "status": [],
    }


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "data").mkdir(parents=True)
    (DIST / "static").mkdir(parents=True)

    shutil.copy2(APP_STATIC / "styles.css", DIST / "static" / "styles.css")
    shutil.copy2(APP_STATIC / "app.js", DIST / "static" / "app.js")
    html = (APP_STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace("<body>", '<body data-static="1">', 1)
    (DIST / "index.html").write_text(html, encoding="utf-8")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    links_by: dict[int, list[dict]] = {}
    for r in conn.execute("SELECT runner_id, label, url FROM links ORDER BY id"):
        links_by.setdefault(r["runner_id"], []).append(
            {"label": r["label"], "url": r["url"]}
        )
    races_by: dict[int, list[dict]] = {}
    for r in conn.execute(
        "SELECT runner_id, raced_on, label FROM races ORDER BY sort_key"
    ):
        races_by.setdefault(r["runner_id"], []).append(
            {"raced_on": r["raced_on"], "label": r["label"]}
        )

    runners = [
        row_to_runner(
            r,
            links_by.get(r["id"], []),
            races_by.get(r["id"], []),
        )
        for r in conn.execute(
            "SELECT * FROM runners ORDER BY stars DESC, points DESC, name COLLATE NOCASE"
        )
    ]

    countries = [
        {"code": r["country"], "name": r["country_name"], "flag": r["flag"]}
        for r in conn.execute(
            """
            SELECT country, country_name, flag, COUNT(*) AS n
            FROM runners GROUP BY country ORDER BY n DESC, country_name
            """
        )
    ]
    stars = [
        {"stars": r["stars"], "count": r["n"]}
        for r in conn.execute(
            "SELECT stars, COUNT(*) AS n FROM runners GROUP BY stars ORDER BY stars DESC"
        )
    ]
    event_seasons = [
        r["season"]
        for r in conn.execute(
            "SELECT DISTINCT season FROM events ORDER BY season DESC"
        )
    ]
    meta = {
        "total": len(runners),
        "with_profile": sum(1 for r in runners if r["has_profile"]),
        "countries": countries,
        "stars": stars,
        "events_total": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "event_seasons": event_seasons,
    }

    events = []
    for r in conn.execute(
        """
        SELECT * FROM events
        ORDER BY
          CASE WHEN date_start IS NULL OR date_start = '' THEN 1 ELSE 0 END,
          date_start, name COLLATE NOCASE
        """
    ):
        events.append(
            {
                "id": r["id"],
                "season": r["season"],
                "calendar": r["calendar"],
                "name": r["name"],
                "country": r["country"],
                "country_code": r["country_code"],
                "region": r["region"],
                "date_label": r["date_label"],
                "date_start": r["date_start"],
                "distances": r["distances"],
                "notes": r["notes"],
                "status": r["status"],
                "championship": bool(r["championship"]),
                "grandmaster": bool(r["grandmaster"]),
                "is_final": bool(r["is_final"]),
                "is_gm_only": bool(r["is_gm_only"]),
                "announcement_url": r["announcement_url"] or "",
                "report_url": r["report_url"] or "",
                "results_url": r["results_url"] or "",
                "source_url": r["source_url"],
            }
        )

    event_countries = [
        {"code": r["country_code"], "name": r["country"], "count": r["n"]}
        for r in conn.execute(
            """
            SELECT country_code, country, COUNT(*) AS n FROM events
            WHERE country_code IS NOT NULL AND country_code != ''
            GROUP BY country_code ORDER BY n DESC, country
            """
        )
    ]

    rts_races = []
    try:
        for r in conn.execute(
            """
            SELECT * FROM rts_races
            ORDER BY
              CASE WHEN year IS NULL THEN 1 ELSE 0 END,
              year DESC, name COLLATE NOCASE
            """
        ):
            years = json.loads(r["years"]) if r["years"] else []
            rts_races.append(
                {
                    "rts_result_id": r["rts_result_id"],
                    "name": r["name"],
                    "distances": r["distances"],
                    "year": r["year"],
                    "years": years,
                    "title": r["title"],
                    "url": r["url"],
                    "export_url": r["export_url"],
                    "finisher_count": r["finisher_count"],
                }
            )
        rts_years = [
            r["year"]
            for r in conn.execute(
                "SELECT DISTINCT year FROM rts_races WHERE year IS NOT NULL ORDER BY year DESC"
            )
        ]
    except sqlite3.OperationalError:
        rts_years = []

    conn.close()

    def write(name: str, payload: object) -> None:
        path = DIST / "data" / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"  {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")

    write("meta.json", meta)
    write("runners.json", {"total": len(runners), "runners": runners})
    write(
        "events.json",
        {
            "total": len(events),
            "seasons": event_seasons,
            "countries": event_countries,
            "events": events,
        },
    )
    write(
        "rts-races.json",
        {"total": len(rts_races), "years": rts_years, "races": rts_races},
    )

    # Cloudflare Pages: SPA-ish headers optional
    (DIST / "_headers").write_text(
        "/*\n  X-Frame-Options: DENY\n  X-Content-Type-Options: nosniff\n",
        encoding="utf-8",
    )
    print(f"exported {DIST}")


if __name__ == "__main__":
    main()
