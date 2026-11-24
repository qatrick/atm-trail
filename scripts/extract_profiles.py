import json
import pathlib
import re

ROOT = pathlib.Path(r"c:\Users\user\src\trail")
sm = (
    ROOT.parent.parent
    / ".cursor"
    / "projects"
    / "c-Users-user-src-trail"
    / "agent-tools"
    / "c5b76882-b033-48f6-bb12-c295b5f0a9f9.txt"
)
# agent-tools path may vary; try known path
candidates = [
    pathlib.Path(
        r"C:\Users\user\.cursor\projects\c-Users-user-src-trail\agent-tools\c5b76882-b033-48f6-bb12-c295b5f0a9f9.txt"
    ),
]
sm_text = candidates[0].read_text(encoding="utf-8")
urls = re.findall(r"https?://(?:www\.)?asiatrailmaster\.com/\S+", sm_text)
urls = sorted({u.rstrip("/.,)").split("?")[0] for u in urls})
print("unique site urls", len(urls))

single = []
for u in urls:
    path = re.sub(r"https?://(?:www\.)?asiatrailmaster\.com/?", "", u)
    if path and "/" not in path and not path.startswith("s/"):
        single.append(path)
print("single segment", len(single))

runners = json.loads((ROOT / "data" / "grandmasters.json").read_text(encoding="utf-8"))


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


slugs = {slugify(r["name"]): r["name"] for r in runners}

KNOWN_NON = {
    "multimedia",
    "search",
    "news",
    "legends",
    "partners",
    "join-us",
    "guidebook",
    "definition",
    "objectives",
    "benefits",
    "conditions-of-entry",
    "media-1",
    "grandmaster-database",
    "the-grandmasters-copy",
    "the-asia-trail-grandmaster-quest",
    "hall-of-fame",
    "atm-champions",
    "championship-podium",
    "atm-race-winners",
    "grandmasters",
    "friends",
    "home",
    "about",
    "contact",
    "shop",
    "store",
    "cart",
    "config",
    "account",
    "schedule",
    "calendar",
    "results",
    "rankings",
    "announcement",
}

exact = [p for p in single if p in slugs]
print("exact slug matches", len(exact))

# fuzzy: page slug equals or starts with runner slug or vice versa
profile_map = {}
for p in single:
    if p.lower() in KNOWN_NON:
        continue
    for slug, name in slugs.items():
        if p == slug or p.startswith(slug + "-") or (len(p) > 5 and slug.startswith(p)):
            profile_map.setdefault(name, []).append(p)
            break

print("runners with profile pages", len(profile_map))
for name, paths in list(profile_map.items())[:25]:
    print(f"  {name}: {paths}")

# also dump all single-segment pages not in known_non for manual review
other = [p for p in single if p.lower() not in KNOWN_NON and p not in {x for xs in profile_map.values() for x in xs}]
print("other pages", len(other))
print(other[:50])

out = {
    "runners_with_profiles": {
        name: [f"https://www.asiatrailmaster.com/{p}" for p in paths]
        for name, paths in profile_map.items()
    },
    "all_single_segment": single,
}
(ROOT / "data" / "profile_urls.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
)
print("wrote profile_urls.json")
