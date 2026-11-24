"""Fill DUV links for every runner — auto when sure, best-guess otherwise."""
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
UA = "Mozilla/5.0 (compatible; ATM-Grandmaster-Archive/1.0)"


@dataclass
class Candidate:
    runner_id: str
    name: str
    nat: str
    gender: str
    yob: str
    span: str
    club: str = ""
    residence: str = ""
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


def parse_person_page(html: str) -> Candidate | None:
    rid_m = re.search(r"RunnerID:\s*</b></td>\s*<td[^>]*>\s*(\d+)", html, re.I)
    if not rid_m:
        rid_m = re.search(r"getresultperson\.php\?runner=(\d+)", html, re.I)
    if not rid_m:
        return None
    name_m = re.search(r"Name:\s*</b></td>\s*<td[^>]*>\s*([^<]+)", html, re.I)
    nat_m = re.search(r"Nationality:\s*</b></td>\s*<td[^>]*>\s*([A-Z]{3})", html, re.I)
    gender = ""
    yob_m = re.search(r"Year of birth:\s*</b></td>\s*<td[^>]*>\s*(\d{4})", html, re.I)
    years = [int(y) for y in re.findall(r">\s*(20\d\d)\s*<", html)]
    span = f"{min(years)}-{max(years)}" if years else ""
    return Candidate(
        runner_id=rid_m.group(1),
        name=clean(name_m.group(1)) if name_m else "",
        nat=nat_m.group(1) if nat_m else "",
        gender=gender,
        yob=yob_m.group(1) if yob_m else "",
        span=span,
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
                    break
        out.append(
            Candidate(
                runner_id=rid,
                name=name,
                nat=nat,
                gender=gender[:1].upper() if gender else "",
                yob=yob,
                span=span,
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
    qs = []
    if len(parts) >= 2:
        qs.append(f"{parts[-1]}, {' '.join(parts[:-1])}")
        qs.append(f"{parts[0]}, {' '.join(parts[1:])}")
        # drop middle particles for long names
        if len(parts) >= 3:
            qs.append(f"{parts[-1]}, {parts[0]}")
            qs.append(f"{parts[-1]}, {parts[0]} {parts[1]}")
        qs.append(parts[-1])
        qs.append(parts[0])
    else:
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


def span_end(span: str) -> int:
    m = re.search(r"(\d{4})\s*$", span or "")
    return int(m.group(1)) if m else 0


def score_candidate(c: Candidate, country: str, gender: str, full_name: str) -> Candidate:
    score = 0.0
    reasons = []
    if c.nat and c.nat == country:
        score += 100
        reasons.append("nat")
    elif c.nat:
        score -= 30
        reasons.append("nat_mismatch")

    g = (gender or "").upper()[:1]
    if c.gender and g and c.gender == g:
        score += 40
        reasons.append("gender")
    elif c.gender and g and c.gender != g:
        score -= 40
        reasons.append("gender_mismatch")

    end = span_end(c.span)
    if end >= 2024:
        score += 35
    elif end >= 2020:
        score += 25
    elif end >= 2016:
        score += 10
    elif end and end < 2015:
        score -= 5

    tokens = {t.lower() for t in re.split(r"[\s,]+", full_name) if t}
    ctokens = {t.lower() for t in re.split(r"[\s,]+", c.name) if t}
    overlap = tokens & ctokens
    score += len(overlap) * 12
    if tokens and tokens.issubset(ctokens):
        score += 50
        reasons.append("subset")
    if ctokens and ctokens.issubset(tokens):
        score += 30
        reasons.append("have_subset")
    # family token match
    fam = c.name.split(",")[0].strip().lower() if "," in c.name else ""
    if fam and fam in tokens:
        score += 25
        reasons.append("family")
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


def classify(best: Candidate, second: float, n: int) -> str:
    if best.score >= 150 and best.score - second >= 25:
        return "auto_strong"
    if n == 1 and best.nat and best.score >= 90:
        return "auto_only"
    if best.score >= 120 and best.score - second >= 40:
        return "auto_gap"
    if best.score >= 80:
        return "guess"
    if best.score >= 40:
        return "guess_weak"
    return "guess_weak"


def main() -> None:
    cache = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    runners = conn.execute(
        "SELECT id, name, country, gender, duv_url, duv_match_status, duv_runner_id, duv_name, duv_match_score FROM runners ORDER BY id"
    ).fetchall()

    need = []
    keep = 0
    for r in runners:
        st = r["duv_match_status"] or ""
        # Re-search anyone without a URL, or no_results. Keep solid autos/seeds/reviews that already have URL.
        if r["duv_url"] and st.startswith(("seed", "auto", "review", "ambiguous", "guess")):
            keep += 1
            continue
        need.append(r)

    log(f"already linked: {keep}; to (re)search: {len(need)}")

    filled = 0
    still_miss = 0

    for i, r in enumerate(need, 1):
        queries = name_queries(r["name"])
        all_cands: dict[str, Candidate] = {}
        for qi, q in enumerate(queries):
            # allow broader surname search for misses
            for c in search_duv(q):
                all_cands[c.runner_id] = c
            time.sleep(0.18)
            # early stop if we already have a strong nat+name hit
            scored = [
                score_candidate(c, r["country"], r["gender"] or "", r["name"])
                for c in all_cands.values()
            ]
            scored.sort(key=lambda c: c.score, reverse=True)
            if scored and scored[0].score >= 160 and scored[0].nat == r["country"]:
                break
            # don't explode on common surnames unless still empty
            if qi >= 2 and len(all_cands) > 30:
                break

        if not all_cands:
            conn.execute(
                """
                UPDATE runners
                SET duv_match_status='no_results', duv_url=NULL, duv_runner_id=NULL,
                    duv_name=NULL, duv_match_score=NULL
                WHERE id=?
                """,
                (r["id"],),
            )
            still_miss += 1
            log(f"[{i}/{len(need)}] MISS {r['name']}")
            cache[str(r["id"])] = {
                "done": True,
                "atm_name": r["name"],
                "status": "no_results",
            }
            continue

        scored = [
            score_candidate(c, r["country"], r["gender"] or "", r["name"])
            for c in all_cands.values()
        ]
        scored.sort(key=lambda c: c.score, reverse=True)
        best = scored[0]
        second = scored[1].score if len(scored) > 1 else -999
        status = classify(best, second, len(scored))
        url = f"https://statistik.d-u-v.org/getresultperson.php?runner={best.runner_id}"

        conn.execute(
            """
            UPDATE runners
            SET duv_runner_id=?, duv_url=?, duv_match_status=?, duv_match_score=?, duv_name=?
            WHERE id=?
            """,
            (best.runner_id, url, status, best.score, best.name, r["id"]),
        )
        filled += 1
        cache[str(r["id"])] = {
            "done": True,
            "atm_name": r["name"],
            "country": r["country"],
            "status": status,
            "duv_runner_id": best.runner_id,
            "duv_url": url,
            "duv_name": best.name,
            "score": best.score,
            "reasons": best.reasons,
            "candidates": [asdict(c) for c in scored[:6]],
        }
        log(
            f"[{i}/{len(need)}] {status.upper()} {r['name']} -> {best.name} "
            f"({best.runner_id}) {best.nat} score={best.score:.0f} cands={len(scored)}"
        )

        if i % 15 == 0:
            conn.commit()
            CACHE_PATH.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    # Also promote existing review/ambiguous rows to guess (they already have URLs)
    promoted = conn.execute(
        """
        UPDATE runners
        SET duv_match_status = CASE
          WHEN duv_match_status IN ('review', 'ambiguous_close') THEN 'guess'
          ELSE duv_match_status
        END
        WHERE duv_url IS NOT NULL
          AND duv_match_status IN ('review', 'ambiguous_close')
        """
    ).rowcount
    conn.commit()
    CACHE_PATH.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    total = conn.execute(
        "SELECT COUNT(*) FROM runners WHERE duv_url IS NOT NULL"
    ).fetchone()[0]
    by = conn.execute(
        "SELECT duv_match_status, COUNT(*) FROM runners GROUP BY duv_match_status"
    ).fetchall()
    conn.close()
    log(f"filled={filled} still_miss={still_miss} promoted={promoted}")
    log(f"with_url={total}/432 status={list(by)}")


if __name__ == "__main__":
    main()
