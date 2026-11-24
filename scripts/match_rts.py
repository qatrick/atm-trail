"""Match ATM grandmasters to Race Timing Solutions (Stone Age) profiles."""
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
CACHE_PATH = DATA / "rts_matches.json"
UA = "Mozilla/5.0 (compatible; ATM-Grandmaster-Archive/1.0)"

# Manual seeds from known profiles
SEED = {
    # atm name lower -> rts id
    "patrick cheung kashing": "107984",  # user example
    "ellen yin kwan cheng": "102160",
    "hisashi kitamura": "107989",
    "ruth theresia": "101970",
    "aleksis capili": "100254",
    "kim matthews": "103114",
    "tahira najmunisaa muhammad zaid": "100165",
    "fredelyn alberto": "113450",
    # Habiba Benahmed (100012) is on RTS but not in current GM list
}

NAT_MAP = {
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
    "usa": "USA",
    "canada": "CAN",
    "vietnam": "VIE",
    "italy": "ITA",
    "united kingdom": "GBR",
    "great britain": "GBR",
    "norway": "NOR",
    "south korea": "KOR",
    "korea": "KOR",
    "belgium": "BEL",
    "france": "FRA",
}


@dataclass
class Candidate:
    runner_id: str
    given: str
    family: str
    score: float = 0
    reasons: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.given} {self.family}".strip()


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def tokens(name: str) -> set[str]:
    return {t for t in norm(name).split() if t and t not in {"bin", "binti", "van", "de", "da", "del"}}


def search_queries(full_name: str) -> list[str]:
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    if not parts:
        return []
    qs = []
    # family name (last token) is usually best on RTS
    qs.append(parts[-1])
    if len(parts) >= 2:
        qs.append(f"{parts[0]} {parts[-1]}")
        qs.append(" ".join(parts))
        qs.append(parts[0])
    # unique
    seen = set()
    out = []
    for q in qs:
        k = q.lower()
        if k in seen or len(q) < 2:
            continue
        seen.add(k)
        out.append(q)
    return out


def parse_search(html: str) -> list[Candidate]:
    out: list[Candidate] = []
    # rows contain profile?id=ID linked with given/family nearby
    # From snapshot: links are separate for id, given, family
    # Parse table rows if present
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S):
        row = m.group(1)
        ids = re.findall(r"profile\?id=(\d+)", row)
        if not ids:
            continue
        rid = ids[0]
        names = [clean(x) for x in re.findall(r"profile\?id=\d+[^\"]*\"[^>]*>([^<]+)", row)]
        # typically [id_text, given, family] or [given, family]
        given, family = "", ""
        name_parts = [n for n in names if not n.isdigit()]
        if len(name_parts) >= 2:
            given, family = name_parts[0], name_parts[1]
        elif len(name_parts) == 1:
            given = name_parts[0]
        out.append(Candidate(runner_id=rid, given=given, family=family))

    if out:
        # dedupe
        seen = set()
        uniq = []
        for c in out:
            if c.runner_id in seen:
                continue
            seen.add(c.runner_id)
            uniq.append(c)
        return uniq

    # fallback: collect id + following name links from body text order
    links = re.findall(
        r'href=\"[^\"]*profile\?id=(\d+)\"[^>]*>([^<]*)</a>', html, re.I
    )
    # group by id sequence: id, given, family often repeat same id thrice
    by_id: dict[str, list[str]] = {}
    for rid, text in links:
        by_id.setdefault(rid, [])
        t = clean(text)
        if t and t != rid and t not in by_id[rid]:
            by_id[rid].append(t)
    for rid, names in by_id.items():
        given = names[0] if names else ""
        family = names[1] if len(names) > 1 else ""
        out.append(Candidate(runner_id=rid, given=given, family=family))
    return out


def score_candidate(c: Candidate, full_name: str) -> Candidate:
    score = 0.0
    reasons = []
    want = tokens(full_name)
    have = tokens(c.full_name) | tokens(c.given) | tokens(c.family)
    if not have:
        c.score = 0
        return c
    overlap = want & have
    score += len(overlap) * 25
    reasons.append(f"overlap:{len(overlap)}")
    if want and want.issubset(have):
        score += 80
        reasons.append("subset")
    if have and have.issubset(want):
        score += 40
        reasons.append("have_subset")
    # exact normalized equality (order-insensitive)
    if want == have:
        score += 100
        reasons.append("exact_tokens")
    if norm(c.full_name) == norm(full_name):
        score += 40
        reasons.append("exact_string")
    # family / given appear anywhere in ATM name (handles "Patrick Cheung Kashing")
    fam = norm(c.family)
    giv = norm(c.given)
    if fam and fam in want:
        score += 45
        reasons.append("family_in_name")
    if giv and giv in want:
        score += 35
        reasons.append("given_in_name")
    parts = full_name.split()
    if parts and fam == norm(parts[-1]):
        score += 15
        reasons.append("family_last")
    if parts and giv == norm(parts[0]):
        score += 10
        reasons.append("given_first")
    c.score = score
    c.reasons = ",".join(reasons)
    return c


def profile_race_count(runner_id: str) -> int:
    try:
        html = fetch(f"https://m.racetimingsolutions.com/profile?id={runner_id}")
    except Exception:
        return 0
    # count result table rows with a year
    return len(re.findall(r">\s*20\d\d\s*<", html))


def break_ties(scored: list[Candidate]) -> list[Candidate]:
    """When top scores tie, prefer the profile with actual race history."""
    if len(scored) < 2:
        return scored
    top = scored[0].score
    tied = [c for c in scored if abs(c.score - top) < 1e-6]
    if len(tied) <= 1:
        return scored
    enriched = []
    for c in tied[:4]:
        races = profile_race_count(c.runner_id)
        time.sleep(0.15)
        enriched.append((races, -int(c.runner_id), c))
        log(f"  tie-break {c.runner_id} {c.full_name}: {races} races")
    enriched.sort(reverse=True)
    winner = enriched[0][2]
    rest = [c for c in scored if c.runner_id != winner.runner_id]
    return [winner, *rest]


def pick_best(cands: list[Candidate], full_name: str) -> tuple[Candidate | None, str]:
    if not cands:
        return None, "no_results"
    scored = [score_candidate(c, full_name) for c in cands]
    scored.sort(key=lambda c: c.score, reverse=True)
    scored = break_ties(scored)
    best, second = scored[0], scored[1].score if len(scored) > 1 else -1
    # Both given+family tokens present in ATM name is a strong fingerprint
    want = tokens(full_name)
    strong_name = bool(
        norm(best.family) in want and norm(best.given) in want and len(want) >= 2
    )
    if strong_name and (best.score - second >= 15 or second < 0) and best.score >= 100:
        return best, "auto_name_pair"
    # after tie-break, identical names with clear race-history winner
    if strong_name and best.score >= 200:
        return best, "auto_name_pair"
    if best.score >= 150 and best.score - second >= 20:
        return best, "auto_strong"
    if best.score >= 130 and len([c for c in scored if c.score >= best.score - 10]) == 1:
        return best, "auto_unique"
    if best.score >= 120 and best.score - second >= 40:
        return best, "auto_gap"
    if best.score >= 100:
        return best, "review"
    return best, "weak"


def search_rts(query: str) -> list[Candidate]:
    q = urllib.parse.quote(query)
    url = f"https://m.racetimingsolutions.com/rankings/athlete-search/{q}"
    try:
        html = fetch(url)
    except urllib.error.HTTPError as e:
        log(f"  HTTP {e.code} for {query}")
        return []
    return parse_search(html)


def ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runners)")}
    for col, typ in [
        ("rts_runner_id", "TEXT"),
        ("rts_url", "TEXT"),
        ("rts_match_status", "TEXT"),
        ("rts_match_score", "REAL"),
        ("rts_name", "TEXT"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE runners ADD COLUMN {col} {typ}")


def apply_seed(conn: sqlite3.Connection, runners: list) -> int:
    n = 0
    by_name = {norm(r["name"]): r for r in runners}
    for name, rid in SEED.items():
        row = by_name.get(norm(name))
        if not row:
            # fuzzy contains
            hits = [r for r in runners if norm(name) in norm(r["name"]) or norm(r["name"]) in norm(name)]
            row = hits[0] if len(hits) == 1 else None
        if not row:
            continue
        url = f"https://m.racetimingsolutions.com/profile?id={rid}"
        conn.execute(
            """
            UPDATE runners
            SET rts_runner_id=?, rts_url=?, rts_match_status=?, rts_match_score=?, rts_name=?
            WHERE id=?
            """,
            (rid, url, "seed", 999, name.title(), row["id"]),
        )
        n += 1
        log(f"SEED {row['name']} -> {rid}")
    return n


def main() -> None:
    cache: dict = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)
    runners = conn.execute(
        "SELECT id, name, country, gender FROM runners ORDER BY id"
    ).fetchall()

    seeded = apply_seed(conn, runners)
    conn.commit()

    linked = seeded
    review = 0
    missing = 0

    def db_exec(sql: str, params: tuple = ()) -> None:
        for attempt in range(20):
            try:
                conn.execute(sql, params)
                return
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower():
                    raise
                time.sleep(1.5)
        conn.execute(sql, params)

    for i, r in enumerate(runners, 1):
        key = str(r["id"])
        # skip if already has an RTS link in DB
        existing = conn.execute(
            "SELECT rts_match_status, rts_runner_id FROM runners WHERE id=?",
            (r["id"],),
        ).fetchone()
        if existing and existing["rts_runner_id"]:
            st = existing["rts_match_status"] or ""
            if st.startswith("auto") or st == "seed":
                linked += 1
            elif st in {"review", "weak"}:
                review += 1
            else:
                missing += 1
            continue
        if key in cache and cache[key].get("done"):
            st = cache[key].get("status", "")
            if st.startswith("auto") or st == "seed":
                linked += 1
            elif st in {"review", "weak"}:
                review += 1
            else:
                missing += 1
            # still ensure DB has it
            if cache[key].get("rts_runner_id"):
                db_exec(
                    """
                    UPDATE runners
                    SET rts_runner_id=?, rts_url=?, rts_match_status=?, rts_match_score=?, rts_name=?
                    WHERE id=?
                    """,
                    (
                        cache[key]["rts_runner_id"],
                        cache[key]["rts_url"],
                        cache[key]["status"],
                        cache[key].get("score"),
                        cache[key].get("rts_name"),
                        r["id"],
                    ),
                )
            continue

        queries = search_queries(r["name"])
        all_cands: dict[str, Candidate] = {}
        for q in queries[:3]:
            for c in search_rts(q):
                all_cands[c.runner_id] = c
            time.sleep(0.2)

        best, status = pick_best(list(all_cands.values()), r["name"])
        entry = {
            "done": True,
            "atm_name": r["name"],
            "queries": queries,
            "status": status,
            "candidates": [
                asdict(score_candidate(c, r["name"]))
                for c in sorted(
                    all_cands.values(),
                    key=lambda x: -score_candidate(x, r["name"]).score,
                )[:8]
            ],
        }

        if best and status.startswith("auto"):
            url = f"https://m.racetimingsolutions.com/profile?id={best.runner_id}"
            entry.update(
                {
                    "rts_runner_id": best.runner_id,
                    "rts_url": url,
                    "rts_name": best.full_name,
                    "score": best.score,
                }
            )
            db_exec(
                """
                UPDATE runners
                SET rts_runner_id=?, rts_url=?, rts_match_status=?, rts_match_score=?, rts_name=?
                WHERE id=?
                """,
                (best.runner_id, url, status, best.score, best.full_name, r["id"]),
            )
            linked += 1
            log(
                f"[{i}/{len(runners)}] LINK {r['name']} -> {best.full_name} ({best.runner_id}) "
                f"score={best.score:.0f} [{status}]"
            )
        elif best and status in {"review", "weak"}:
            url = f"https://m.racetimingsolutions.com/profile?id={best.runner_id}"
            entry.update(
                {
                    "rts_runner_id": best.runner_id,
                    "rts_url": url,
                    "rts_name": best.full_name,
                    "score": best.score,
                }
            )
            db_exec(
                """
                UPDATE runners
                SET rts_runner_id=?, rts_url=?, rts_match_status=?, rts_match_score=?, rts_name=?
                WHERE id=?
                """,
                (best.runner_id, url, status, best.score, best.full_name, r["id"]),
            )
            review += 1
            log(
                f"[{i}/{len(runners)}] REVIEW {r['name']} ~ {best.full_name} ({best.runner_id}) "
                f"score={best.score:.0f} [{status}]"
            )
        else:
            db_exec(
                """
                UPDATE runners
                SET rts_runner_id=NULL, rts_url=NULL, rts_match_status=?, rts_match_score=NULL, rts_name=NULL
                WHERE id=?
                """,
                (status, r["id"]),
            )
            missing += 1
            log(f"[{i}/{len(runners)}] MISS {r['name']}")

        cache[key] = entry
        if i % 15 == 0:
            CACHE_PATH.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            for _ in range(10):
                try:
                    conn.commit()
                    break
                except sqlite3.OperationalError:
                    time.sleep(1.5)

    for _ in range(10):
        try:
            conn.commit()
            break
        except sqlite3.OperationalError:
            time.sleep(1.5)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    conn.close()
    log(f"done linked={linked} review={review} missing={missing}")


if __name__ == "__main__":
    main()
