"""Scrape ATM race results from m.racetimingsolutions.com/rankings/result/{id}.

Strategy:
1. Harvest result IDs (+ year) from every grandmaster RTS profile we already linked.
2. Also probe low contiguous IDs (1..N) for early races missing from profiles.
3. Fetch each unique result page for race title / distance / finisher rows.
4. Store rts_races + rts_results in SQLite; write JSON archive.
"""
from __future__ import annotations

import html as htmlmod
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = DATA / "grandmasters.db"
OUT_RACES = DATA / "rts_races.json"
OUT_PROGRESS = DATA / "rts_results_progress.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ATM-Archive/1.0)"}

LOW_ID_SCAN = 120  # early seasons used dense small IDs
SLEEP = 0.18
MAX_RETRIES = 3


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str) -> str:
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(0.6 * (attempt + 1))
    raise last  # type: ignore[misc]


def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return htmlmod.unescape(re.sub(r"\s+", " ", s)).strip()


def parse_distance(label: str) -> str:
    m = re.search(
        r"(\d+(?:\.\d+)?\s*(?:km|mi|miles?|k)\b)",
        label,
        re.I,
    )
    return m.group(1).replace(" ", "") if m else ""


def parse_race_name(title_or_label: str) -> tuple[str, str]:
    """Return (name, distance) from 'Asia Trail Master Series | Foo 42km' or '42km / Foo'."""
    t = htmlmod.unescape(title_or_label).strip()
    t = re.sub(r"^Asia Trail Master Series\s*\|\s*", "", t, flags=re.I).strip()
    # profile style: "42km / Race Name"
    m = re.match(r"^(\d+(?:\.\d+)?\s*(?:km|mi|miles?|k))\s*/\s*(.+)$", t, re.I)
    if m:
        return m.group(2).strip(), m.group(1).replace(" ", "")
    dist = parse_distance(t)
    name = t
    if dist:
        name = re.sub(re.escape(dist), "", name, flags=re.I).strip(" -|/")
        name = re.sub(r"\s+", " ", name).strip()
    return name, dist


def harvest_ids_from_profiles(conn: sqlite3.Connection) -> dict[int, dict]:
    """result_id -> {years:set, labels:set}"""
    rows = conn.execute(
        """
        SELECT rts_runner_id FROM runners
        WHERE rts_runner_id IS NOT NULL AND CAST(rts_runner_id AS TEXT) != ''
        """
    ).fetchall()
    ids = [str(r[0]) for r in rows]
    log(f"harvesting result ids from {len(ids)} RTS profiles")
    found: dict[int, dict] = {}
    for i, rid in enumerate(ids, 1):
        url = f"https://m.racetimingsolutions.com/profile?id={rid}"
        try:
            html = fetch(url)
        except Exception as e:
            log(f"  [{i}/{len(ids)}] profile {rid} FAIL {e}")
            continue
        # <td>2016</td><td><a ... href=".../rankings/result/1">42km / Beach...</a>
        for year, result_id, label in re.findall(
            r"<td>\s*(\d{4})\s*</td>\s*<td>\s*<a[^>]+href=\"[^\"]*?/rankings/result/(\d+)\"[^>]*>(.*?)</a>",
            html,
            re.I | re.S,
        ):
            rid_i = int(result_id)
            entry = found.setdefault(rid_i, {"years": set(), "labels": set()})
            entry["years"].add(int(year))
            entry["labels"].add(strip_tags(label))
        if i % 25 == 0 or i == len(ids):
            log(f"  [{i}/{len(ids)}] unique result ids so far: {len(found)}")
        time.sleep(SLEEP)
    return found


def probe_low_ids(known: dict[int, dict]) -> None:
    log(f"probing low result ids 1..{LOW_ID_SCAN}")
    for i in range(1, LOW_ID_SCAN + 1):
        if i in known:
            continue
        url = f"https://m.racetimingsolutions.com/rankings/result/{i}"
        try:
            html = fetch(url)
        except urllib.error.HTTPError:
            continue
        except Exception as e:
            log(f"  {i} err {e}")
            continue
        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if not title:
            continue
        t = strip_tags(title.group(1))
        if "Log In" in t:
            continue
        known[i] = {"years": set(), "labels": {t}}
        log(f"  found low id {i}: {t[:80]}")
        time.sleep(SLEEP)


def parse_result_page(html: str, result_id: int) -> tuple[dict, list[dict]]:
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    span = re.search(r'class="title">(.*?)</span>', html, re.I | re.S)
    raw_title = strip_tags(title.group(1) if title else "")
    header = strip_tags(span.group(1) if span else raw_title)
    name, dist = parse_race_name(header if header else raw_title)
    if not dist:
        name2, dist = parse_race_name(raw_title)
        if name2:
            name = name2

    # parse finisher table rows
    table = re.search(r"<table>(.*?)</table>", html, re.I | re.S)
    finishers: list[dict] = []
    if table:
        rows = re.findall(r"<tr>(.*?)</tr>", table.group(1), re.I | re.S)
        if rows:
            headers = [strip_tags(h).lower() for h in re.findall(r"<th[^>]*>(.*?)</th>", rows[0], re.I | re.S)]
            # expected: atm id, first, last, other, bib, nationality, gender, finish time, overall, gender pos, ...
            for row in rows[1:]:
                cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)]
                if len(cells) < 8:
                    continue
                id_m = re.search(r"profile\?id=(\d+)", row)
                rts_id = id_m.group(1) if id_m else (cells[0] if cells[0].isdigit() else "")
                # nationality cell may include flag junk already stripped
                nat = cells[5] if len(cells) > 5 else ""
                finishers.append(
                    {
                        "rts_runner_id": rts_id,
                        "first_name": cells[1] if len(cells) > 1 else "",
                        "last_name": cells[2] if len(cells) > 2 else "",
                        "other_name": cells[3] if len(cells) > 3 else "",
                        "bib": cells[4] if len(cells) > 4 else "",
                        "nationality": nat,
                        "gender": cells[6] if len(cells) > 6 else "",
                        "finish_time": cells[7] if len(cells) > 7 else "",
                        "overall_pos": cells[8] if len(cells) > 8 else "",
                        "gender_pos": cells[9] if len(cells) > 9 else "",
                        "finisher_points": cells[10] if len(cells) > 10 else "",
                        "performance_points": cells[11] if len(cells) > 11 else "",
                        "bonus_points": cells[12] if len(cells) > 12 else "",
                        "total_points": cells[13] if len(cells) > 13 else "",
                    }
                )

    race = {
        "rts_result_id": result_id,
        "name": name,
        "distances": dist,
        "title": raw_title,
        "header": header,
        "url": f"https://m.racetimingsolutions.com/rankings/result/{result_id}",
        "export_url": f"https://m.racetimingsolutions.com/rankings/result/exportasexcel/{result_id}",
        "finisher_count": len(finishers),
    }
    return race, finishers


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS rts_races (
          rts_result_id INTEGER PRIMARY KEY,
          name TEXT,
          distances TEXT,
          year INTEGER,
          years TEXT,
          title TEXT,
          url TEXT,
          export_url TEXT,
          finisher_count INTEGER DEFAULT 0,
          source TEXT
        );
        CREATE TABLE IF NOT EXISTS rts_results (
          id INTEGER PRIMARY KEY,
          rts_result_id INTEGER NOT NULL,
          rts_runner_id TEXT,
          first_name TEXT,
          last_name TEXT,
          other_name TEXT,
          bib TEXT,
          nationality TEXT,
          gender TEXT,
          finish_time TEXT,
          overall_pos TEXT,
          gender_pos TEXT,
          finisher_points TEXT,
          performance_points TEXT,
          bonus_points TEXT,
          total_points TEXT,
          UNIQUE(rts_result_id, rts_runner_id, bib)
        );
        CREATE INDEX IF NOT EXISTS idx_rts_results_runner ON rts_results(rts_runner_id);
        CREATE INDEX IF NOT EXISTS idx_rts_results_race ON rts_results(rts_result_id);
        CREATE INDEX IF NOT EXISTS idx_rts_races_year ON rts_races(year);
        """
    )


def main() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_schema(conn)

    progress: dict = {}
    if OUT_PROGRESS.exists():
        progress = json.loads(OUT_PROGRESS.read_text(encoding="utf-8"))

    harvested = harvest_ids_from_profiles(conn)
    # merge years/labels into serializable progress seed
    seed = {
        str(k): {
            "years": sorted(v["years"]),
            "labels": sorted(v["labels"]),
        }
        for k, v in harvested.items()
    }
    probe_map = {int(k): {"years": set(v["years"]), "labels": set(v["labels"])} for k, v in seed.items()}
    probe_low_ids(probe_map)

    result_ids = sorted(probe_map.keys())
    log(f"fetching {len(result_ids)} result pages")

    races_out: list[dict] = []
    done = set(progress.get("done_ids", []))

    for i, rid in enumerate(result_ids, 1):
        meta = probe_map[rid]
        if rid in done and progress.get("races", {}).get(str(rid)):
            race = progress["races"][str(rid)]
            races_out.append(race)
            if i % 50 == 0:
                log(f"  [{i}/{len(result_ids)}] cached {rid}")
            continue

        url = f"https://m.racetimingsolutions.com/rankings/result/{rid}"
        try:
            html = fetch(url)
            race, finishers = parse_result_page(html, rid)
        except Exception as e:
            log(f"  [{i}/{len(result_ids)}] {rid} FAIL {e}")
            continue

        years = sorted(meta.get("years") or [])
        race["years"] = years
        race["year"] = years[0] if len(years) == 1 else (max(years) if years else None)
        if not race["name"] and meta.get("labels"):
            label = next(iter(meta["labels"]))
            n, d = parse_race_name(label)
            race["name"] = n
            race["distances"] = race["distances"] or d
        race["source"] = "rts_result"

        conn.execute(
            """
            INSERT INTO rts_races (
              rts_result_id, name, distances, year, years, title, url, export_url, finisher_count, source
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(rts_result_id) DO UPDATE SET
              name=excluded.name,
              distances=excluded.distances,
              year=excluded.year,
              years=excluded.years,
              title=excluded.title,
              url=excluded.url,
              export_url=excluded.export_url,
              finisher_count=excluded.finisher_count,
              source=excluded.source
            """,
            (
                rid,
                race["name"],
                race["distances"],
                race["year"],
                json.dumps(years),
                race["title"],
                race["url"],
                race["export_url"],
                race["finisher_count"],
                race["source"],
            ),
        )
        conn.execute("DELETE FROM rts_results WHERE rts_result_id=?", (rid,))
        for f in finishers:
            conn.execute(
                """
                INSERT OR IGNORE INTO rts_results (
                  rts_result_id, rts_runner_id, first_name, last_name, other_name, bib,
                  nationality, gender, finish_time, overall_pos, gender_pos,
                  finisher_points, performance_points, bonus_points, total_points
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rid,
                    f["rts_runner_id"],
                    f["first_name"],
                    f["last_name"],
                    f["other_name"],
                    f["bib"],
                    f["nationality"],
                    f["gender"],
                    f["finish_time"],
                    f["overall_pos"],
                    f["gender_pos"],
                    f["finisher_points"],
                    f["performance_points"],
                    f["bonus_points"],
                    f["total_points"],
                ),
            )
        conn.commit()

        races_out.append(race)
        done.add(rid)
        progress["done_ids"] = sorted(done)
        progress.setdefault("races", {})[str(rid)] = race
        if i % 10 == 0 or i == len(result_ids):
            OUT_PROGRESS.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")
            log(
                f"  [{i}/{len(result_ids)}] {rid} {race['name'][:50]} "
                f"({race['distances']}) n={race['finisher_count']} year={race['year']}"
            )
        time.sleep(SLEEP)

    OUT_RACES.write_text(json.dumps(races_out, indent=2, ensure_ascii=False), encoding="utf-8")
    n_races = conn.execute("SELECT COUNT(*) FROM rts_races").fetchone()[0]
    n_res = conn.execute("SELECT COUNT(*) FROM rts_results").fetchone()[0]
    by_year = conn.execute(
        "SELECT year, COUNT(*) FROM rts_races GROUP BY year ORDER BY year"
    ).fetchall()
    conn.close()
    log(f"done races={n_races} finishers={n_res} by_year={by_year}")
    log(f"wrote {OUT_RACES}")


if __name__ == "__main__":
    main()
