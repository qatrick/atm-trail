from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import connect

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

app = FastAPI(title="ATM Grandmasters")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _col(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def row_to_runner(row: Any, links: list[dict] | None = None) -> dict:
    rts_url = _col(row, "rts_url")
    duv_url = _col(row, "duv_url")
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
        "has_profile": bool(row["has_profile"]),
        "rts_runner_id": _col(row, "rts_runner_id"),
        "rts_url": rts_url,
        "rts_match_status": _col(row, "rts_match_status"),
        "duv_runner_id": _col(row, "duv_runner_id"),
        "duv_url": duv_url,
        "duv_match_status": _col(row, "duv_match_status"),
        "links": links or [],
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta() -> dict:
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM runners").fetchone()["n"]
        with_profile = conn.execute(
            "SELECT COUNT(*) AS n FROM runners WHERE has_profile = 1"
        ).fetchone()["n"]
        countries = [
            {"code": r["country"], "name": r["country_name"], "flag": r["flag"]}
            for r in conn.execute(
                """
                SELECT country, country_name, flag, COUNT(*) AS n
                FROM runners
                GROUP BY country
                ORDER BY n DESC, country_name
                """
            )
        ]
        stars = [
            {"stars": r["stars"], "count": r["n"]}
            for r in conn.execute(
                "SELECT stars, COUNT(*) AS n FROM runners GROUP BY stars ORDER BY stars DESC"
            )
        ]
        events_total = 0
        event_seasons: list[int] = []
        try:
            events_total = conn.execute(
                "SELECT COUNT(*) AS n FROM events"
            ).fetchone()["n"]
            event_seasons = [
                r["season"]
                for r in conn.execute(
                    "SELECT DISTINCT season FROM events ORDER BY season DESC"
                )
            ]
        except Exception:
            pass
    return {
        "total": total,
        "with_profile": with_profile,
        "countries": countries,
        "stars": stars,
        "events_total": events_total,
        "event_seasons": event_seasons,
    }


def row_to_event(row: Any) -> dict:
    return {
        "id": row["id"],
        "season": row["season"],
        "calendar": row["calendar"],
        "name": row["name"],
        "country": row["country"],
        "country_code": row["country_code"],
        "region": row["region"],
        "date_label": row["date_label"],
        "date_start": row["date_start"],
        "distances": row["distances"],
        "notes": row["notes"],
        "status": row["status"],
        "championship": bool(row["championship"]),
        "grandmaster": bool(row["grandmaster"]),
        "is_final": bool(row["is_final"]),
        "is_gm_only": bool(row["is_gm_only"]),
        "announcement_url": _col(row, "announcement_url") or "",
        "report_url": _col(row, "report_url") or "",
        "results_url": _col(row, "results_url") or "",
        "source_url": row["source_url"],
    }


@app.get("/api/events")
def list_events(
    q: str | None = None,
    season: int | None = None,
    calendar: str | None = None,
    country: str | None = None,
) -> dict:
    clauses: list[str] = []
    params: list[Any] = []
    if q:
        needle = f"%{q.strip()}%"
        clauses.append("(name LIKE ? OR region LIKE ? OR country LIKE ?)")
        params.extend([needle, needle, needle])
    if season is not None:
        clauses.append("season = ?")
        params.append(season)
    if calendar:
        clauses.append("calendar = ?")
        params.append(calendar.lower())
    if country:
        clauses.append("country_code = ?")
        params.append(country.upper())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT * FROM events
        {where}
        ORDER BY
          CASE WHEN date_start IS NULL OR date_start = '' THEN 1 ELSE 0 END,
          date_start,
          name COLLATE NOCASE
    """
    with connect() as conn:
        try:
            rows = conn.execute(sql, params).fetchall()
            total = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        countries = [
            {"code": r["country_code"], "name": r["country"], "count": r["n"]}
            for r in conn.execute(
                """
                SELECT country_code, country, COUNT(*) AS n
                FROM events
                WHERE country_code IS NOT NULL AND country_code != ''
                GROUP BY country_code
                ORDER BY n DESC, country
                """
            )
        ]
        seasons = [
            r["season"]
            for r in conn.execute(
                "SELECT DISTINCT season FROM events ORDER BY season DESC"
            )
        ]
    return {
        "total": total,
        "count": len(rows),
        "seasons": seasons,
        "countries": countries,
        "events": [row_to_event(r) for r in rows],
    }


@app.get("/api/rts-races")
def list_rts_races(
    q: str | None = None,
    year: int | None = None,
) -> dict:
    clauses: list[str] = []
    params: list[Any] = []
    if q:
        needle = f"%{q.strip()}%"
        clauses.append("(name LIKE ? OR title LIKE ? OR distances LIKE ?)")
        params.extend([needle, needle, needle])
    if year is not None:
        clauses.append("year = ?")
        params.append(year)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT * FROM rts_races
        {where}
        ORDER BY
          CASE WHEN year IS NULL THEN 1 ELSE 0 END,
          year DESC,
          name COLLATE NOCASE
    """
    with connect() as conn:
        try:
            rows = conn.execute(sql, params).fetchall()
            total = conn.execute("SELECT COUNT(*) AS n FROM rts_races").fetchone()["n"]
        except Exception:
            return {"total": 0, "count": 0, "years": [], "races": []}
        years = [
            r["year"]
            for r in conn.execute(
                "SELECT DISTINCT year FROM rts_races WHERE year IS NOT NULL ORDER BY year DESC"
            )
        ]
    races = [
        {
            "rts_result_id": r["rts_result_id"],
            "name": r["name"],
            "distances": r["distances"],
            "year": r["year"],
            "years": json.loads(r["years"]) if r["years"] else [],
            "title": r["title"],
            "url": r["url"],
            "export_url": r["export_url"],
            "finisher_count": r["finisher_count"],
        }
        for r in rows
    ]
    return {"total": total, "count": len(races), "years": years, "races": races}


@app.get("/api/runners")
def list_runners(
    q: str | None = None,
    stars: int | None = Query(default=None, ge=1, le=4),
    country: str | None = None,
    gender: str | None = None,
    has_profile: bool | None = None,
) -> dict:
    clauses: list[str] = []
    params: list[Any] = []

    if q:
        clauses.append("name LIKE ?")
        params.append(f"%{q.strip()}%")
    if stars is not None:
        clauses.append("stars = ?")
        params.append(stars)
    if country:
        clauses.append("country = ?")
        params.append(country.upper())
    if gender:
        clauses.append("gender = ?")
        params.append(gender.upper()[:1])
    if has_profile is not None:
        clauses.append("has_profile = ?")
        params.append(1 if has_profile else 0)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT * FROM runners
        {where}
        ORDER BY stars DESC, points DESC, name COLLATE NOCASE
    """

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT COUNT(*) AS n FROM runners").fetchone()["n"]
        ids = [r["id"] for r in rows]
        links_by: dict[int, list[dict]] = {i: [] for i in ids}
        if ids:
            placeholders = ",".join("?" * len(ids))
            for link in conn.execute(
                f"SELECT runner_id, label, url FROM links WHERE runner_id IN ({placeholders}) ORDER BY id",
                ids,
            ):
                links_by[link["runner_id"]].append(
                    {"label": link["label"], "url": link["url"]}
                )

    runners = [row_to_runner(r, links_by[r["id"]]) for r in rows]
    return {"total": total, "count": len(runners), "runners": runners}


@app.get("/api/runners/{runner_id}")
def get_runner(runner_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM runners WHERE id = ?", (runner_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Runner not found")
        links = [
            {"label": r["label"], "url": r["url"]}
            for r in conn.execute(
                "SELECT label, url FROM links WHERE runner_id = ? ORDER BY id",
                (runner_id,),
            )
        ]
        races = [
            {"raced_on": r["raced_on"], "label": r["label"]}
            for r in conn.execute(
                "SELECT raced_on, label FROM races WHERE runner_id = ? ORDER BY sort_key",
                (runner_id,),
            )
        ]
        status = []
        # status lines live only in JSON archive; optional later

    data = row_to_runner(row, links)
    data["races"] = races
    data["status"] = status
    data["profile_heading"] = row["profile_heading"]
    return data
