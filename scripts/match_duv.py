"""Match ATM grandmasters to DUV runner profiles.

Writes progress to data/duv_matches.json, then upserts into SQLite.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = DATA / "grandmasters.db"
CACHE_PATH = DATA / "duv_matches.json"
SOURCE = DATA / "grandmasters.json"
UA = "Mozilla/5.0 (compatible; ATM-Grandmaster-Archive/1.0)"

SEED = {
    "hisashi kitamura": "1001076",
    "masafumi yamamoto": "1011667",
    "ruth theresia": "739893",
    "jay ofonda": "2122322",
    "cecille wael": "1059507",
    "rachel chan pui hong": "907597",
    "tracy choi ma yan": "2126417",
}


@dataclass
class Candidate:
    runner_id: str
    name: str
    nat: str
    gender: str
    yob: str
    span: str
    club: str
    residence: str
    score: float = 0
    reasons: str = ""


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


def clean(text: str) -> str:
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def parse_person_page(html: str) -> Candidate | None:
    rid_m = re.search(r"RunnerID:\s*</b></td>\s*<td[^>]*>\s*(\d+)", html, re.I)
    if not rid_m:
        rid_m = re.search(r"getresultperson\.php\?runner=(\d+)", html, re.I)
    if not rid_m:
        return None
    name_m = re.search(r"Name:\s*</b></td>\s*<td[^>]*>\s*([^<]+)", html, re.I)
    nat_m = re.search(r"Nationality:\s*</b></td>\s*<td[^>]*>\s*([A-Z]{3})", html, re.I)
    gender = ""
    g_m = re.search(r"\b(Male|Female|M/F:\s*[MF])\b", html, re.I)
    if g_m:
        g = g_m.group(1).upper()
        gender = "F" if "F" in g else "M"
    yob_m = re.search(r"Year of birth:\s*</b></td>\s*<td[^>]*>\s*(\d{4})", html, re.I)
    years = [int(y) for y in re.findall(r">\s*(20\d\d)\s*<", html)]
    span = f"{min(years)}-{max(years)}" if years else ""
    club_m = re.search(r"Club:\s*</b></td>\s*<td[^>]*>\s*([^<]*)", html, re.I)
    res_m = re.search(r"Residence:\s*</b></td>\s*<td[^>]*>\s*([^<]*)", html, re.I)
    return Candidate(
        runner_id=rid_m.group(1),
        name=clean(name_m.group(1)) if name_m else "",
        nat=nat_m.group(1) if nat_m else "",
        gender=gender,
        yob=yob_m.group(1) if yob_m else "",
        span=span,
        club=clean(club_m.group(1)) if club_m else "",
        residence=clean(res_m.group(1)) if res_m else "",
    )


def parse_search(html: str) -> list[Candidate]:
    if "Searching the Name" not in html and (
        "RunnerID:" in html or "getresultperson.php?runner=" in html
    ):
        person = parse_person_page(html)
        return [person] if person else []

    out: list[Candidate] = []
    for m in re.finditer(
        r'getresultperson\.php\?runner=(\d+)[^>]*>\s*([^<]+?)\s*</a>(.*?)</tr>',
        html,
        re.I | re.S,
    ):
        rid, name, rest_html = m.group(1), clean(m.group(2)), m.group(3)
        cells = [
            clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", rest_html, re.I | re.S)
        ]
        while cells and cells[0] == "":
            cells = cells[1:]
        club = cells[1] if len(cells) > 1 else ""
        residence = cells[2] if len(cells) > 2 else ""
        nat = cells[3] if len(cells) > 3 else ""
        gender = cells[4] if len(cells) > 4 else ""
        yob = cells[5] if len(cells) > 5 else ""
        span = cells[6] if len(cells) > 6 else ""
        if nat and not re.fullmatch(r"[A-Z]{3}", nat):
            for i, c in enumerate(cells):
                if re.fullmatch(r"[A-Z]{3}", c):
                    nat = c
                    gender = cells[i + 1] if i + 1 < len(cells) else ""
                    yob = cells[i + 2] if i + 2 < len(cells) else ""
                    span = cells[i + 3] if i + 3 < len(cells) else ""
                    club = cells[i - 2] if i >= 2 else club
                    residence = cells[i - 1] if i >= 1 else residence
                    break
        out.append(
            Candidate(
                runner_id=rid,
                name=name,
                nat=nat,
                gender=gender[:1].upper() if gender else "",
                yob=yob,
                span=span,
                club=club,
                residence=residence,
            )
        )
    seen = set()
    uniq = []
    for c in out:
        if c.runner_id in seen:
            continue
        seen.add(c.runner_id)
        uniq.append(c)
    return uniq


def name_queries(full_name: str) -> list[str]:
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    if not parts:
        return []
    queries = []
    if len(parts) == 1:
        queries.append(parts[0])
    else:
        queries.append(f"{parts[-1]}, {' '.join(parts[:-1])}")
        if len(parts) >= 2:
            queries.append(f"{parts[0]}, {' '.join(parts[1:])}")
        queries.append(parts[-1])
    seen = set()
    out = []
    for q in queries:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def span_end(span: str) -> int:
    m = re.search(r"(\d{4})\s*$", span or "")
    return int(m.group(1)) if m else 0


def span_start(span: str) -> int:
    m = re.search(r"^(\d{4})", span or "")
    return int(m.group(1)) if m else 0


def score_candidate(
    c: Candidate, country: str, gender: str, full_name: str
) -> Candidate:
    score = 0.0
    reasons = []
    if c.nat and c.nat == country:
        score += 100
        reasons.append("nat")
    elif c.nat:
        score -= 40
        reasons.append("nat_mismatch")

    g = (gender or "").upper()[:1]
    if c.gender and g and c.gender == g:
        score += 40
        reasons.append("gender")
    elif c.gender and g and c.gender != g:
        score -= 50
        reasons.append("gender_mismatch")

    end = span_end(c.span)
    start = span_start(c.span)
    if end >= 2024:
        score += 35
        reasons.append("very_recent")
    elif end >= 2020:
        score += 25
        reasons.append("recent")
    elif end >= 2016:
        score += 10
        reasons.append("mid")
    elif end and end < 2015:
        score -= 10
        reasons.append("old")

    if start and end:
        score += min(end - start + 1, 12) * 1.5

    tokens = {t.lower() for t in re.split(r"[\s,]+", full_name) if t}
    ctokens = {t.lower() for t in re.split(r"[\s,]+", c.name) if t}
    overlap = len(tokens & ctokens)
    score += overlap * 8
    if overlap >= min(2, len(tokens)):
        reasons.append(f"name_overlap:{overlap}")

    c.score = score
    c.reasons = ",".join(reasons)
    return c


def search_duv(query: str) -> list[Candidate]:
    qs = urllib.parse.urlencode({"sname": query, "language": "EN"})
    url = f"https://statistik.d-u-v.org/searchrunner.php?{qs}"
    try:
        html = fetch(url)
    except urllib.error.HTTPError as e:
        log(f"  HTTP {e.code} for {query}")
        return []
    return parse_search(html)


def pick_best(
    candidates: list[Candidate], country: str, gender: str, full_name: str
) -> tuple[Candidate | None, str]:
    if not candidates:
        return None, "no_results"
    scored = [score_candidate(c, country, gender, full_name) for c in candidates]
    scored.sort(key=lambda c: c.score, reverse=True)
    best = scored[0]
    second = scored[1].score if len(scored) > 1 else -999

    if best.score >= 150 and best.score - second >= 25:
        return best, "auto_strong"
    if best.score >= 140 and best.nat == country and (
        best.gender == (gender or "").upper()[:1] or not gender
    ):
        peers = [
            c
            for c in scored
            if c.nat == country
            and (not gender or c.gender == gender.upper()[:1])
            and c.score >= best.score - 15
        ]
        if len(peers) == 1:
            return best, "auto_unique_nat"
        if len(peers) > 1:
            peers.sort(key=lambda c: (span_end(c.span), c.score), reverse=True)
            top = peers[0]
            if len(peers) == 1 or span_end(top.span) > span_end(peers[1].span):
                return top, "auto_most_recent"
            return top, "ambiguous_close"
    if best.score >= 120 and best.nat == country and len(scored) == 1:
        return best, "auto_only"
    if best.score >= 100 and best.nat == country and best.score - second >= 40:
        return best, "auto_clear_gap"
    # single precise hit with nat match is enough
    if len(scored) == 1 and best.nat == country and best.score >= 90:
        return best, "auto_only"
    return best, "review"


def apply_to_db(cache: dict) -> None:
    for attempt in range(30):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=60)
            conn.execute("PRAGMA journal_mode=WAL")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(runners)")}
            for col, typ in [
                ("duv_runner_id", "TEXT"),
                ("duv_url", "TEXT"),
                ("duv_match_status", "TEXT"),
                ("duv_match_score", "REAL"),
                ("duv_name", "TEXT"),
            ]:
                if col not in cols:
                    conn.execute(f"ALTER TABLE runners ADD COLUMN {col} {typ}")

            runners = {
                r[0]: r[1]
                for r in conn.execute("SELECT id, name FROM runners").fetchall()
            }
            # reverse map name -> id
            by_norm = {norm_name(n): i for i, n in runners.items()}

            applied = 0
            for key, entry in cache.items():
                if key == "_meta" or not entry.get("done"):
                    continue
                rid = None
                # cache keys are atm runner ids as strings when available
                if key.isdigit() and int(key) in runners:
                    rid = int(key)
                else:
                    rid = by_norm.get(norm_name(entry.get("atm_name", "")))
                if rid is None:
                    continue
                if entry.get("duv_runner_id"):
                    conn.execute(
                        """
                        UPDATE runners
                        SET duv_runner_id=?, duv_url=?, duv_match_status=?,
                            duv_match_score=?, duv_name=?
                        WHERE id=?
                        """,
                        (
                            entry["duv_runner_id"],
                            entry.get("duv_url"),
                            entry.get("status"),
                            entry.get("score"),
                            entry.get("duv_name"),
                            rid,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE runners
                        SET duv_runner_id=NULL, duv_url=NULL, duv_match_status=?,
                            duv_match_score=NULL, duv_name=NULL
                        WHERE id=?
                        """,
                        (entry.get("status"), rid),
                    )
                applied += 1
            conn.commit()
            conn.close()
            log(f"applied {applied} DUV matches to SQLite")
            return
        except sqlite3.OperationalError as e:
            log(f"DB busy ({e}); retry {attempt + 1}/30")
            time.sleep(2)
    log("WARNING: could not apply DUV matches to DB; cache saved")


def main() -> None:
    runners = json.loads(SOURCE.read_text(encoding="utf-8"))
    # attach stable ids 1..n matching load_db order
    for i, r in enumerate(runners, 1):
        r["_id"] = i

    cache: dict = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    # seeds
    for r in runners:
        n = norm_name(r["name"])
        if n in SEED:
            rid = SEED[n]
            cache[str(r["_id"])] = {
                "done": True,
                "atm_name": r["name"],
                "country": r["country"],
                "gender": r.get("gender"),
                "status": "seed",
                "duv_runner_id": rid,
                "duv_url": f"https://statistik.d-u-v.org/getresultperson.php?runner={rid}",
                "duv_name": r["name"],
                "score": 999,
            }
            log(f"SEED {r['name']} -> {rid}")

    linked = 0
    review = 0
    missing = 0

    for i, r in enumerate(runners, 1):
        key = str(r["_id"])
        if key in cache and cache[key].get("done"):
            st = cache[key].get("status", "")
            if st.startswith("auto") or st == "seed":
                linked += 1
            elif st in {"review", "ambiguous_close"}:
                review += 1
            else:
                missing += 1
            continue

        queries = name_queries(r["name"])
        all_cands: dict[str, Candidate] = {}
        best = None
        status = "no_results"
        for qi, q in enumerate(queries):
            if qi > 0 and "," not in q and len(all_cands) >= 1:
                tentative, tstatus = pick_best(
                    list(all_cands.values()),
                    r["country"],
                    r.get("gender") or "",
                    r["name"],
                )
                if tentative and tstatus.startswith("auto"):
                    best, status = tentative, tstatus
                    break
            if qi >= 2 and "," not in q:
                continue
            for c in search_duv(q):
                all_cands[c.runner_id] = c
            time.sleep(0.2)
            best, status = pick_best(
                list(all_cands.values()),
                r["country"],
                r.get("gender") or "",
                r["name"],
            )
            if best and status.startswith("auto"):
                break

        if best is None and all_cands:
            best, status = pick_best(
                list(all_cands.values()),
                r["country"],
                r.get("gender") or "",
                r["name"],
            )

        entry = {
            "done": True,
            "atm_name": r["name"],
            "country": r["country"],
            "gender": r.get("gender"),
            "queries": queries,
            "status": status,
            "candidates": [
                asdict(
                    score_candidate(
                        c, r["country"], r.get("gender") or "", r["name"]
                    )
                )
                for c in sorted(
                    all_cands.values(),
                    key=lambda x: -score_candidate(
                        x, r["country"], r.get("gender") or "", r["name"]
                    ).score,
                )[:8]
            ],
        }
        if best:
            entry.update(
                {
                    "duv_runner_id": best.runner_id,
                    "duv_url": f"https://statistik.d-u-v.org/getresultperson.php?runner={best.runner_id}",
                    "duv_name": best.name,
                    "score": best.score,
                    "reasons": best.reasons,
                }
            )

        cache[key] = entry
        if best and status.startswith("auto"):
            linked += 1
            log(
                f"[{i}/{len(runners)}] LINK {r['name']} -> {best.name} ({best.runner_id}) "
                f"{best.nat} {best.span} score={best.score:.0f} [{status}]"
            )
        elif best:
            review += 1
            log(
                f"[{i}/{len(runners)}] REVIEW {r['name']} ~ {best.name} ({best.runner_id}) "
                f"score={best.score:.0f} [{status}]"
            )
        else:
            missing += 1
            log(f"[{i}/{len(runners)}] MISS {r['name']}")

        if i % 10 == 0:
            CACHE_PATH.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    CACHE_PATH.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log(f"done linked={linked} review={review} missing={missing}")
    apply_to_db(cache)


if __name__ == "__main__":
    main()
