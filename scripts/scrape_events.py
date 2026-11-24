"""Scrape ATM season overview calendars into SQLite events table."""
from __future__ import annotations

import html as htmlmod
import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = DATA / "grandmasters.db"
OUT_JSON = DATA / "events.json"
UA = "Mozilla/5.0 (compatible; ATM-Grandmaster-Archive/1.0)"

CALENDAR_DB_URL = "https://www.asiatrailmaster.com/atm-calendar-database"
CALENDAR_DB_SEASON = 12

SEASON_PAGES = [
    {
        "season": 11,
        "label": "Season XI",
        "url": "https://www.asiatrailmaster.com/s11-overview",
    },
    {
        "season": 10,
        "label": "Season X",
        "url": "https://www.asiatrailmaster.com/2024-atm-championship-calendar",
    },
    {
        "season": 9,
        "label": "Season IX",
        "url": "https://www.asiatrailmaster.com/2024-atm-season-ix-overview",
    },
    {
        "season": 8,
        "label": "Season VIII",
        "url": "https://www.asiatrailmaster.com/2023-atm-season-viii-overview",
    },
    {
        "season": 7,
        "label": "Season VII",
        "url": "https://www.asiatrailmaster.com/2022-atm-calendar",
    },
]

CODE_TO_COUNTRY = {
    "PHI": "Philippines",
    "MAS": "Malaysia",
    "SIN": "Singapore",
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
    "LAO": "Laos",
    "NEP": "Nepal",
    "NPL": "Nepal",
    "MYA": "Myanmar",
    "MGL": "Mongolia",
    "CHN": "China",
    "TPE": "Taiwan",
    "FRA": "France",
    "BAN": "Bangladesh",
    "BRU": "Brunei",
}

COUNTRY_TO_CODE = {
    "philippines": "PHI",
    "malaysia": "MAS",
    "brunei": "BRU",
    "singapore": "SGP",
    "indonesia": "INA",
    "hong kong": "HKG",
    "india": "IND",
    "japan": "JPN",
    "australia": "AUS",
    "thailand": "THA",
    "united states": "USA",
    "canada": "CAN",
    "vietnam": "VIE",
    "italy": "ITA",
    "united kingdom": "GBR",
    "norway": "NOR",
    "south korea": "KOR",
    "korea": "KOR",
    "belgium": "BEL",
    "laos": "LAO",
    "nepal": "NEP",
    "myanmar": "MYA",
    "mongolia": "MGL",
    "china": "CHN",
    "taiwan": "TPE",
    "france": "FRA",
}

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</(p|div|li|h\d|tr)>", "\n", html, flags=re.I)
    html = re.sub(r"<li[^>]*>", "\n- ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = html.replace("\xa0", " ").replace("&nbsp;", " ")
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n\s*\n+", "\n", html)
    return html


def expand_year(y: str, season: int) -> int:
    yi = int(y)
    if yi >= 100:
        return yi
    # two-digit: 25/26/27 relative to season window
    return 2000 + yi


def season_start_year(season: int) -> int:
    """ATM Sn roughly runs Oct (2014+n) – Sep (2015+n)."""
    return 2014 + int(season)


def guess_year_from_season(season: int | None, month: int) -> int | None:
    """Guess calendar year for a month within an ATM season (Oct–Sep)."""
    if season is None:
        return None
    try:
        start = season_start_year(season)
    except (TypeError, ValueError):
        return None
    # Oct–Dec belong to the opening calendar year; Jan–Sep to the next
    return start if month >= 10 else start + 1


def parse_date_blob(blob: str, season: int) -> tuple[str | None, str]:
    """Return (iso_start, original_date_text). Year may be guessed from season."""
    raw = blob.strip()
    if re.search(r"\b(tbc|xx)\b", raw, re.I):
        return None, raw

    # examples: 18/19 Oct 2025 | 25 Oct 2025 | 1-3 May 26 | 18/19 Oct 2025
    m = re.search(
        r"(?P<d1>\d{1,2})(?:/(?P<d2>\d{1,2})|-(?P<d3>\d{1,2}))?\s+"
        r"(?P<mon>[A-Za-z]+)\.?\s+(?P<year>\d{2,4})",
        raw,
    )
    year: int | None = None
    mon: int | None = None
    day: int | None = None
    if m:
        mon = MONTHS.get(m.group("mon").lower().rstrip("."))
        if mon:
            year = expand_year(m.group("year"), season)
            day = int(m.group("d1"))
    else:
        # yearless: "11 December", "9/10 Dec", "1-3 May"
        m2 = re.search(
            r"(?P<d1>\d{1,2})(?:/(?P<d2>\d{1,2})|-(?P<d3>\d{1,2}))?\s+"
            r"(?P<mon>[A-Za-z]+)\.?\b",
            raw,
        )
        if m2:
            mon = MONTHS.get(m2.group("mon").lower().rstrip("."))
            if mon:
                day = int(m2.group("d1"))
                year = guess_year_from_season(season, mon)

    if not mon or not day or not year:
        return None, raw
    try:
        return f"{year:04d}-{mon:02d}-{day:02d}", raw
    except Exception:
        return None, raw


def label_has_explicit_year(label: str) -> bool:
    if re.search(r"\b(?:19|20)\d{2}\b", label):
        return True
    # "Oct 2025" / "Oct 25" after the month token
    return bool(
        re.search(
            r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{2,4}\b",
            label,
            re.I,
        )
    )


def fill_missing_date_start(e: dict) -> dict:
    """Backfill date_start from date_label + season when year was omitted on the page."""
    e = dict(e)
    season = e.get("season")
    label = re.sub(r"\s*\(~S\d+\s*→\s*\d{4}\)$", "", e.get("date_label") or "").strip()
    e["date_label"] = label
    iso = e.get("date_start") or None
    if not iso and season is not None:
        iso, _ = parse_date_blob(label, int(season))
        if iso:
            e["date_start"] = iso
    if (
        iso
        and season is not None
        and label
        and not label_has_explicit_year(label)
    ):
        e["date_label"] = f"{label} (~S{season} → {iso[:4]})"
    return e


def country_code(name: str) -> str:
    key = name.strip().lower()
    # strip region suffixes like "Mindanao", "Karnataka"
    # often "Philippines - Mindanao" already split; here single token country
    if key in COUNTRY_TO_CODE:
        return COUNTRY_TO_CODE[key]
    # first word
    first = key.split(",")[0].split("-")[0].strip()
    return COUNTRY_TO_CODE.get(first, "")


def parse_event_line(line: str, season: int, calendar: str, source_url: str) -> dict | None:
    line = line.strip().lstrip("-•* ").strip()
    if not line or len(line) < 12:
        return None
    # Must look like a dated race line
    if not re.match(r"^\d{1,2}", line):
        return None
    if " - " not in line:
        return None

    parts = [p.strip() for p in line.split(" - ")]
    if len(parts) < 3:
        return None

    date_raw = parts[0]
    # country may include region: "Philippines - Mindanao" already broken by split —
    # so sometimes parts[1]=Philippines, parts[2]=Mindanao, parts[3]=Race...
    # Detect: if parts[2] looks like place (no km) and parts[3] exists with race name
    country = parts[1]
    rest_idx = 2
    # If next segment has no digits/km and following exists, treat as region
    region = ""
    if len(parts) >= 4 and not re.search(r"\d", parts[2]) and not re.search(
        r"km|mile|mi\b", parts[2], re.I
    ):
        # could be region OR race name. Heuristic: short region words / known regions
        maybe_region = parts[2]
        if len(maybe_region.split()) <= 4 and not re.search(
            r"ultra|trail|race|marathon|quest|final", maybe_region, re.I
        ):
            region = maybe_region
            rest_idx = 3

    if rest_idx >= len(parts):
        return None

    name = parts[rest_idx]
    distances = ""
    notes = []
    for extra in parts[rest_idx + 1 :]:
        if re.search(r"\d+\s*(km|mi|mile)", extra, re.I) or re.search(
            r"\d+/\d+", extra
        ):
            if not distances:
                distances = extra
            else:
                notes.append(extra)
        else:
            notes.append(extra)

    note = " | ".join(notes)
    status = "scheduled"
    low = line.lower()
    if "cancel" in low:
        status = "cancelled"
    elif "postpon" in low:
        status = "postponed"
    elif "tbc" in low or "to be confirmed" in low:
        status = "tbc"

    is_final = 1 if "championship final" in low or "atm final" in low else 0
    is_gm_only = 1 if calendar == "grandmaster" and "championship" not in calendar else 0
    # championship calendar events of 70k+ also count for GM; store both flags
    championship = 1 if calendar == "championship" else 0
    grandmaster = 1 if calendar in {"grandmaster", "championship"} else 0

    date_iso, date_label = parse_date_blob(date_raw, season)
    code = country_code(country)

    return {
        "season": season,
        "calendar": calendar,
        "name": name,
        "country": country,
        "country_code": code,
        "region": region,
        "date_label": date_label,
        "date_start": date_iso,
        "distances": distances,
        "notes": note,
        "status": status,
        "championship": championship,
        "grandmaster": grandmaster,
        "is_final": is_final,
        "is_gm_only": 1 if calendar == "grandmaster" and championship == 0 else 0,
        "announcement_url": "",
        "report_url": "",
        "results_url": "",
        "source_url": source_url,
        "raw": line,
    }


def split_sections(text: str) -> list[tuple[str, str]]:
    """Return list of (calendar_type, section_text)."""
    # Find championship / grandmaster / season headers
    sections: list[tuple[str, str, int]] = []
    patterns = [
        (r"(championship\s+(points\s+)?(races|qualifiers?)|list of atm championship)", "championship"),
        (r"(grandmaster\s+quest)", "grandmaster"),
    ]
    lowers = text.lower()
    hits = []
    for pat, kind in patterns:
        for m in re.finditer(pat, lowers):
            hits.append((m.start(), kind))
    hits.sort()
    if not hits:
        return [("unknown", text)]
    for i, (start, kind) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        sections.append((kind, text[start:end]))
    return sections


def parse_page(html: str, season: int, source_url: str) -> list[dict]:
    text = html_to_text(html)
    events = []
    for calendar, section in split_sections(text):
        for line in section.splitlines():
            line = line.strip()
            if not line.startswith("-") and not re.match(r"^\d{1,2}[/-]", line):
                # also accept bare dated lines
                if not re.match(r"^\d{1,2}.+-.+km", line, re.I):
                    continue
            ev = parse_event_line(line, season, calendar, source_url)
            if ev:
                events.append(ev)
    return events


def extract_js_events_array(html: str) -> list[dict]:
    """Pull `const events = [...]` from the ATM Calendar Database page."""
    m = re.search(r"const\s+events\s*=\s*(\[)", html)
    if not m:
        return []
    start = m.start(1)
    depth = 0
    end = -1
    for i, ch in enumerate(html[start:], start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return []
    return json.loads(html[start : end + 1])


def type_to_flags(event_type: str) -> tuple[str, int, int, int]:
    """Return (calendar, championship, grandmaster, is_gm_only)."""
    t = (event_type or "").strip().lower()
    if "candidate" in t:
        return "candidate", 0, 0, 0
    if "championship" in t or "qualifier" in t:
        return "championship", 1, 1, 0
    if "grandmaster" in t:
        return "grandmaster", 0, 1, 1
    return "unknown", 0, 0, 0


def normalize_calendar_db_event(raw: dict, season: int, source_url: str) -> dict:
    code = (raw.get("country") or "").strip().upper()
    if code == "SIN":
        code = "SGP"
    if code == "NPL":
        code = "NEP"
    country = CODE_TO_COUNTRY.get(code, code)
    location = (raw.get("location") or "").strip()
    region = ""
    if "," in location:
        # "Santa Cruz, Mindanao" -> region Mindanao when last part looks geographic
        parts = [p.strip() for p in location.split(",")]
        if len(parts) >= 2:
            region = parts[-1]
    calendar, championship, grandmaster, is_gm_only = type_to_flags(raw.get("type", ""))
    date_label = (raw.get("date") or "").strip()
    date_start = (raw.get("date_sort") or "").strip() or None
    status = "scheduled"
    low = f"{date_label} {raw.get('name','')}".lower()
    if "cancel" in low:
        status = "cancelled"
    elif "tbc" in low or date_label.upper().startswith("XX") or "/XX" in date_label.upper():
        status = "tbc"
    elif "postpon" in low:
        status = "postponed"

    announcement = (raw.get("announcement") or "").strip()
    report = (raw.get("report") or "").strip()
    results = (raw.get("results") or "").strip()
    notes_bits = []
    if announcement:
        notes_bits.append(f"announcement:{announcement}")
    if report:
        notes_bits.append(f"report:{report}")
    if results:
        notes_bits.append(f"results:{results}")

    return {
        "season": season,
        "calendar": calendar,
        "name": (raw.get("name") or "").strip(),
        "country": country,
        "country_code": code,
        "region": region,
        "date_label": date_label,
        "date_start": date_start,
        "distances": (raw.get("races") or "").strip(),
        "notes": " | ".join(notes_bits),
        "status": status,
        "championship": championship,
        "grandmaster": grandmaster,
        "is_final": 0,
        "is_gm_only": is_gm_only,
        "announcement_url": announcement,
        "report_url": report,
        "results_url": results,
        "source_url": source_url,
        "raw": json.dumps(raw, ensure_ascii=False),
    }


def scrape_calendar_db() -> list[dict]:
    log(f"fetch Season XII calendar DB {CALENDAR_DB_URL}")
    html = fetch(CALENDAR_DB_URL)
    raw_events = extract_js_events_array(html)
    log(f"  embedded events array: {len(raw_events)}")
    out = [
        normalize_calendar_db_event(r, CALENDAR_DB_SEASON, CALENDAR_DB_URL)
        for r in raw_events
        if (r.get("name") or "").strip()
    ]
    # persist raw for inspection
    (DATA / "s12_calendar_raw.json").write_text(
        json.dumps(raw_events, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY,
          season INTEGER,
          calendar TEXT,
          name TEXT NOT NULL,
          country TEXT,
          country_code TEXT,
          region TEXT,
          date_label TEXT,
          date_start TEXT,
          distances TEXT,
          notes TEXT,
          status TEXT,
          championship INTEGER DEFAULT 0,
          grandmaster INTEGER DEFAULT 0,
          is_final INTEGER DEFAULT 0,
          is_gm_only INTEGER DEFAULT 0,
          announcement_url TEXT,
          report_url TEXT,
          results_url TEXT,
          source_url TEXT,
          raw TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_season ON events(season);
        CREATE INDEX IF NOT EXISTS idx_events_date ON events(date_start);
        CREATE INDEX IF NOT EXISTS idx_events_country ON events(country_code);
        """
    )
    # migrate older DBs that lack URL columns
    cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    for col in ("announcement_url", "report_url", "results_url"):
        if col not in cols:
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} TEXT")


def normalize_name(name: str) -> str:
    n = htmlmod.unescape(name or "")
    n = n.replace("\xa0", " ")
    n = re.sub(r"\s+", " ", n).strip().lower()
    n = n.replace(" : ", ": ").replace(": ", ":")
    # drop trailing distance suffixes for fingerprinting
    n = re.sub(
        r"[:\s\-–—]*\d+(?:\.\d+)?\s*(?:km|mi|miles?|k)(?:\s*[&/,].*)?$",
        "",
        n,
        flags=re.I,
    )
    n = re.sub(r"\s*\(\s*\d+(?:\.\d+)?\s*(?:km|mi|miles?).*$", "", n, flags=re.I)
    return n.strip(" :-")


def normalize_date_key(e: dict) -> str:
    if e.get("date_start"):
        return str(e["date_start"])
    label = htmlmod.unescape(e.get("date_label") or "")
    label = re.sub(r"\s+", " ", label).strip().lower()
    return label


def content_key(e: dict) -> tuple:
    """Identity of a race edition — season omitted (pages re-list older races)."""
    return (
        normalize_name(e.get("name") or ""),
        normalize_date_key(e),
        (e.get("country_code") or "").upper(),
        (e.get("calendar") or "").lower(),
    )


def inferred_season(date_start: str | None) -> int | None:
    """Map ISO date to ATM season (approx Oct Y – Sep Y+1 → season Y-2014)."""
    if not date_start or len(date_start) < 7:
        return None
    try:
        y = int(date_start[:4])
        m = int(date_start[5:7])
    except ValueError:
        return None
    start_year = y if m >= 10 else y - 1
    season = start_year - 2014
    if 7 <= season <= 20:
        return season
    return None


def richness(e: dict) -> int:
    score = 0
    if e.get("distances"):
        score += 3
    if e.get("announcement_url") or (e.get("notes") or "").startswith("announcement:"):
        score += 2
    if e.get("report_url"):
        score += 1
    if e.get("results_url"):
        score += 1
    if e.get("region"):
        score += 1
    if e.get("date_start"):
        score += 2
    return score


def prefer_event(a: dict, b: dict) -> dict:
    """Choose which duplicate to keep when the same race appears on multiple season pages."""
    inferred = inferred_season(a.get("date_start") or b.get("date_start"))
    if inferred is not None:
        a_match = a.get("season") == inferred
        b_match = b.get("season") == inferred
        if a_match and not b_match:
            return a
        if b_match and not a_match:
            return b
        # both/neither: closer season wins
        if a.get("season") is not None and b.get("season") is not None:
            if abs(a["season"] - inferred) != abs(b["season"] - inferred):
                return a if abs(a["season"] - inferred) < abs(b["season"] - inferred) else b

    ra, rb = richness(a), richness(b)
    if ra != rb:
        return a if ra > rb else b

    # Prefer dedicated season overview over the S10 "championship calendar" archive dump
    def source_penalty(e: dict) -> int:
        u = (e.get("source_url") or "").lower()
        if "championship-calendar" in u and "season" not in u:
            return 2
        return 0

    pa, pb = source_penalty(a), source_penalty(b)
    if pa != pb:
        return a if pa < pb else b

    # Prefer the lower season id when still tied (earlier listing is usually the home season)
    sa, sb = a.get("season") or 99, b.get("season") or 99
    return a if sa <= sb else b


def dedupe_events(events: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    for e in events:
        e = dict(e)
        e["name"] = htmlmod.unescape(e.get("name") or "").strip()
        e["date_label"] = htmlmod.unescape(e.get("date_label") or "").strip()
        e["notes"] = htmlmod.unescape(e.get("notes") or "")
        e["raw"] = htmlmod.unescape(e.get("raw") or "") if isinstance(e.get("raw"), str) else e.get("raw")
        e = fill_missing_date_start(e)
        k = content_key(e)
        if not k[0]:
            continue
        if k not in best:
            best[k] = e
        else:
            best[k] = prefer_event(best[k], e)
    # stable-ish order by date then name
    out = list(best.values())
    out.sort(
        key=lambda x: (
            x.get("date_start") or "9999",
            (x.get("name") or "").lower(),
            x.get("calendar") or "",
        )
    )
    return out


def main() -> None:
    all_events: list[dict] = []

    try:
        all_events.extend(scrape_calendar_db())
    except Exception as e:
        log(f"  FAIL calendar DB {e}")
    time.sleep(0.3)

    for page in SEASON_PAGES:
        log(f"fetch {page['label']} {page['url']}")
        try:
            html = fetch(page["url"])
        except Exception as e:
            log(f"  FAIL {e}")
            continue
        evs = parse_page(html, page["season"], page["url"])
        log(f"  parsed {len(evs)} event lines")
        all_events.extend(evs)
        time.sleep(0.3)

    # Collapse cross-season re-lists; keep champ vs GM as separate rows
    unique = dedupe_events(all_events)
    log(f"deduped {len(all_events)} -> {len(unique)}")

    OUT_JSON.write_text(json.dumps(unique, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote {len(unique)} events -> {OUT_JSON}")

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
                e["raw"],
            ),
        )
    conn.commit()
    by_season = conn.execute(
        "SELECT season, calendar, COUNT(*) FROM events GROUP BY 1,2 ORDER BY 1 DESC, 2"
    ).fetchall()
    conn.close()
    log(f"db counts: {by_season}")


if __name__ == "__main__":
    main()
