"""Scrape ATM Hall of Fame grandmaster profile pages and merge with DB."""
from __future__ import annotations

import csv
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from html import unescape

ROOT = pathlib.Path(r"c:\Users\user\src\trail")
DATA = ROOT / "data"
UA = "Mozilla/5.0 (compatible; ATM-Grandmaster-Archive/1.0)"

# Explicit Hall of Fame profile paths discovered from site + sitemap matches
EXTRA_PATHS = [
    "hisashi-kitamura",
    "masafumi-yamamoto",
    "tomohiro-mizukoshi",
    "ruth-theresia-2",
    "ina-budiyarni-1",
    "ina-budiyarni",
    "lily-suryani-1",
    "isaac-yuen-wan-ho-1",
    "jan-nilsen",
    "jan-nilsen-1",
    "amirul-tuah",
    "rex-see",
    "romualdocalbes",
    "sri-wahyuni",
    "stephen-wiseman",
    "khatrina-visperas",
    "chui-peng-lye",
    "ekin-poe-seng-hoe",
    "sukrit",
    "dendi-dwitiandi",
    "susie-lai",
    "trevor-lim",
    "matnarudin-ibrahim",
    "carrie-jane-stander",
    "karhoe-ng",
    "jay-jamil",
    "akol",
    "sungsik-joh",
    "montha-suntornwit",
    "hafizan-lamin",
    "michael-mclean",
    "cecile-wael",
    "melanie-hingpit",
    "alfie-mendoza",
    "ohmmalaihom",
    "yew-hock-lim",
    "joeffrey-camara",
    "kent-stander",
    "shashwat-rao",
    "siokhar-lim",
    "christine-salazar",
    "nikom-tongjai",
    "ramie-amigleo",
    "fredelyn-alberto",
    "john-ellis",
    "alessandro-sherpa",
    "ali-ajis-rasil",
    "arief-wismoyono",
    "cheryl-bihag",
    "joseph-sibal",
    "kim-matthews",
    "tahira-najmunisaa",
    "shindy-patricia",
    "adelinah-lintanga",
    "aleksis-capili",
    "yim-heng-fatt",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_text(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</p>", "\n", html, flags=re.I)
    html = re.sub(r"</div>", "\n", html, flags=re.I)
    html = re.sub(r"</li>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    text = unescape(html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_races(text: str) -> list[str]:
    races = []
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^\d{1,2}/\d{4}\s*-", line):
            races.append(line)
    return races


def parse_profile(html: str, url: str) -> dict:
    text = extract_text(html)
    m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    title = unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
    title = re.sub(r"\s*[—–-]\s*Asia Trail Master.*$", "", title).strip()

    hm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    heading = ""
    if hm:
        heading = unescape(re.sub(r"<[^>]+>", "", hm.group(1))).strip()
        heading = re.sub(r"\s+", " ", heading)

    races = parse_races(text)
    status_lines = []
    for line in text.splitlines():
        line = line.strip()
        if re.search(r"grandmaster", line, re.I) and len(line) < 220:
            if line.lower() not in {s.lower() for s in status_lines}:
                status_lines.append(line)
        if len(status_lines) >= 10:
            break

    return {
        "url": url,
        "title": title or heading,
        "heading": heading,
        "status": status_lines,
        "races": races,
        "race_count": len(races),
    }


def collect_urls(runners: list[dict]) -> dict[str, str]:
    """url -> best-guess runner name."""
    urls: dict[str, str] = {}
    slugs = {slugify(r["name"]): r["name"] for r in runners}

    meta_path = DATA / "profile_urls.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for name, plist in meta.get("runners_with_profiles", {}).items():
            for u in plist:
                urls[u] = name

    for path in EXTRA_PATHS:
        u = f"https://www.asiatrailmaster.com/{path}"
        if u not in urls:
            # fuzzy match slug to runner
            name = slugs.get(path, "")
            if not name:
                for slug, n in slugs.items():
                    if path.startswith(slug) or slug.startswith(path):
                        name = n
                        break
            urls[u] = name
    return urls


def main() -> None:
    runners = json.loads((DATA / "grandmasters.json").read_text(encoding="utf-8"))
    urls = collect_urls(runners)
    log(f"fetching {len(urls)} profile pages...")

    profiles = []
    failures = []
    for i, (url, name) in enumerate(sorted(urls.items()), 1):
        try:
            html = fetch(url)
            parsed = parse_profile(html, url)
            parsed["matched_runner"] = name or None
            keep = parsed["race_count"] > 0 or any(
                "grandmaster" in s.lower() for s in parsed["status"]
            )
            if keep:
                profiles.append(parsed)
                log(
                    f"[{i}/{len(urls)}] OK {parsed['heading'] or url} "
                    f"races={parsed['race_count']}"
                )
            else:
                log(f"[{i}/{len(urls)}] skip {url}")
        except urllib.error.HTTPError as e:
            failures.append({"url": url, "error": f"HTTP {e.code}"})
            log(f"[{i}/{len(urls)}] FAIL {url} HTTP {e.code}")
        except Exception as e:  # noqa: BLE001
            failures.append({"url": url, "error": str(e)})
            log(f"[{i}/{len(urls)}] FAIL {url} {e}")
        time.sleep(0.15)

    by_slug: dict[str, dict] = {}
    for p in profiles:
        keys = []
        if p.get("matched_runner"):
            keys.append(slugify(p["matched_runner"]))
        if p.get("heading"):
            keys.append(slugify(p["heading"]))
        if p.get("title"):
            keys.append(slugify(p["title"]))
        for k in keys:
            if k:
                by_slug[k] = p

    enriched = []
    for r in runners:
        slug = slugify(r["name"])
        profile = by_slug.get(slug)
        if not profile:
            for k, p in by_slug.items():
                if k.startswith(slug) or slug.startswith(k):
                    profile = p
                    break
        item = dict(r)
        if profile:
            item["profile"] = {
                "url": profile["url"],
                "heading": profile.get("heading"),
                "status": profile["status"],
                "races": profile["races"],
                "race_count": profile["race_count"],
            }
        else:
            item["profile"] = None
        enriched.append(item)

    with_profile = sum(1 for x in enriched if x["profile"])
    log(f"profiles scraped: {len(profiles)}")
    log(f"runners with linked profile: {with_profile}/{len(enriched)}")

    (DATA / "grandmaster_profiles.json").write_text(
        json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (DATA / "grandmasters_full.json").write_text(
        json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (DATA / "scrape_failures.json").write_text(
        json.dumps(failures, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    csv_path = DATA / "grandmasters.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "name",
                "country",
                "gender",
                "stars",
                "points",
                "last",
                "date",
                "link",
                "profile_url",
                "race_count",
            ],
        )
        w.writeheader()
        for x in enriched:
            w.writerow(
                {
                    "name": x["name"],
                    "country": x["country"],
                    "gender": x["gender"],
                    "stars": x["stars"],
                    "points": x["points"],
                    "last": x.get("last", ""),
                    "date": x.get("date", ""),
                    "link": x.get("link", ""),
                    "profile_url": (x["profile"] or {}).get("url", ""),
                    "race_count": (x["profile"] or {}).get("race_count", ""),
                }
            )
    log(f"wrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
