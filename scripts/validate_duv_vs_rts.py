"""Cross-check DUV guesses against RTS profiles; promote when names align.

Also promotes AUS runners whose DUV links were human-verified.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = DATA / "grandmasters.db"
REPORT = DATA / "duv_validation_report.json"
UA = "Mozilla/5.0 (compatible; ATM-Grandmaster-Archive/1.0)"


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(name: str) -> set[str]:
    stop = {"bin", "binti", "van", "de", "da", "del", "jr", "ii", "iii"}
    return {
        t
        for t in re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
        if t and t not in stop and len(t) > 1
    }


def parse_rts(html: str) -> dict:
    text = clean(re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I))
    # Name is usually right after Profile heading; grab first substantial line block
    name = ""
    m = re.search(
        r"Profile\s+([A-Za-z][A-Za-z\s\.\-']{2,80}?)\s+Gender",
        text,
        re.I,
    )
    if m:
        name = m.group(1).strip()
    nat = ""
    nm = re.search(r"Nationality\s+([A-Za-z][A-Za-z\s]+?)(?:\s+Team|\s+ATM|\s+Resident|\s+$)", text)
    if nm:
        nat = nm.group(1).strip()
    gender = ""
    gm = re.search(r"Gender\s+(Male|Female)", text, re.I)
    if gm:
        gender = gm.group(1)[0].upper()
    races = len(re.findall(r"\b20\d\d\b", text))
    return {"name": name, "nat": nat, "gender": gender, "race_mentions": races}


def parse_duv(html: str) -> dict:
    name_m = re.search(r"Name:\s*</b></td>\s*<td[^>]*>\s*([^<]+)", html, re.I)
    nat_m = re.search(r"Nationality:\s*</b></td>\s*<td[^>]*>\s*([A-Z]{3})", html, re.I)
    years = [int(y) for y in re.findall(r">\s*(20\d\d)\s*<", html)]
    return {
        "name": clean(name_m.group(1)) if name_m else "",
        "nat": nat_m.group(1) if nat_m else "",
        "span": f"{min(years)}-{max(years)}" if years else "",
        "events": len(years),
    }


NAT_TO_CODE = {
    "philippines": "PHI",
    "malaysia": "MAS",
    "brunei": "BRU",
    "singapore": "SGP",
    "indonesia": "INA",
    "hong kong": "HKG",
    "hong kong, china": "HKG",
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
    "belgium": "BEL",
    "france": "FRA",
    "china": "CHN",
}


def rts_nat_code(nat: str) -> str:
    return NAT_TO_CODE.get(nat.lower().strip(), "")


def overlap_ok(atm: str, other: str) -> tuple[bool, int]:
    a, b = tokens(atm), tokens(other)
    if not a or not b:
        return False, 0
    n = len(a & b)
    # need at least 2 shared tokens, or 1 if both short
    need = 2 if len(a) >= 2 else 1
    return n >= need, n


def main() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    # 1) Human-verified: AUS guesses → verified_aus
    aus = conn.execute(
        """
        UPDATE runners
        SET duv_match_status='verified_aus'
        WHERE country='AUS'
          AND duv_url IS NOT NULL
          AND (
            duv_match_status LIKE 'guess%'
            OR duv_match_status IN ('review', 'ambiguous_close')
          )
        """
    ).rowcount
    conn.commit()
    log(f"promoted AUS verified: {aus}")

    # 2) Cross-check remaining guesses that also have RTS
    rows = conn.execute(
        """
        SELECT id, name, country, gender, duv_url, duv_runner_id, duv_name,
               duv_match_status, rts_url, rts_runner_id, rts_name
        FROM runners
        WHERE duv_url IS NOT NULL
          AND rts_url IS NOT NULL
          AND (
            duv_match_status LIKE 'guess%'
            OR duv_match_status IN ('review', 'ambiguous_close')
          )
        ORDER BY id
        """
    ).fetchall()
    log(f"to cross-check vs RTS: {len(rows)}")

    report = []
    promoted = 0
    rejected = 0
    unclear = 0

    for i, r in enumerate(rows, 1):
        item = {
            "id": r["id"],
            "name": r["name"],
            "country": r["country"],
            "duv_id": r["duv_runner_id"],
            "rts_id": r["rts_runner_id"],
            "before": r["duv_match_status"],
        }
        try:
            rts = parse_rts(fetch(r["rts_url"]))
            time.sleep(0.15)
            duv = parse_duv(fetch(r["duv_url"]))
            time.sleep(0.15)
        except Exception as e:
            item["result"] = "fetch_error"
            item["error"] = str(e)
            report.append(item)
            unclear += 1
            log(f"[{i}/{len(rows)}] ERR {r['name']}: {e}")
            continue

        item["rts"] = rts
        item["duv"] = duv

        ok_rts, n_rts = overlap_ok(r["name"], rts.get("name") or r["rts_name"] or "")
        ok_duv, n_duv = overlap_ok(r["name"], duv.get("name") or r["duv_name"] or "")
        ok_cross, n_cross = overlap_ok(
            rts.get("name") or "", duv.get("name") or ""
        )
        rts_code = rts_nat_code(rts.get("nat") or "")
        nat_ok = (not rts_code or rts_code == r["country"]) and (
            not duv.get("nat")
            or duv["nat"] == r["country"]
            or (r["country"] == "HKG" and duv["nat"] in {"HKG", "CHN"})
        )

        # Promote when ATM↔DUV name ok AND (RTS name ok or RTS↔DUV name ok) AND nat ok
        if ok_duv and nat_ok and (ok_rts or ok_cross):
            conn.execute(
                "UPDATE runners SET duv_match_status=? WHERE id=?",
                ("verified_rts", r["id"]),
            )
            item["result"] = "promoted"
            item["scores"] = {
                "atm_rts": n_rts,
                "atm_duv": n_duv,
                "rts_duv": n_cross,
                "nat_ok": nat_ok,
            }
            promoted += 1
            log(
                f"[{i}/{len(rows)}] PROMOTE {r['name']} "
                f"DUV={duv.get('name')} RTS={rts.get('name')} "
                f"overlap duv={n_duv} rts={n_rts} cross={n_cross}"
            )
        elif ok_duv and nat_ok and not ok_rts and not ok_cross:
            # DUV looks fine vs ATM but RTS name parse/match weak — leave as guess
            item["result"] = "duv_ok_rts_unclear"
            unclear += 1
            log(f"[{i}/{len(rows)}] KEEP-GUESS {r['name']} (DUV ok, RTS unclear)")
        elif not ok_duv:
            # mark suspect for later review
            conn.execute(
                "UPDATE runners SET duv_match_status=? WHERE id=?",
                ("suspect", r["id"]),
            )
            item["result"] = "suspect"
            rejected += 1
            log(
                f"[{i}/{len(rows)}] SUSPECT {r['name']} "
                f"DUV={duv.get('name')} ATM tokens weak (overlap={n_duv})"
            )
        else:
            item["result"] = "unclear"
            unclear += 1
            log(f"[{i}/{len(rows)}] UNCLEAR {r['name']}")

        report.append(item)
        if i % 20 == 0:
            conn.commit()

    conn.commit()
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    status = conn.execute(
        "SELECT duv_match_status, COUNT(*) FROM runners GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    conn.close()
    log(f"done promoted={promoted} suspect={rejected} unclear={unclear}")
    log(f"status={status}")
    log(f"report -> {REPORT}")


if __name__ == "__main__":
    main()
