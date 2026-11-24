import re
import urllib.request

url = "https://www.asiatrailmaster.com/season-12-atm-calendar-overview"
html = urllib.request.urlopen(
    urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30
).read().decode("utf-8", "replace")

for m in re.finditer(r'href="([^"]+)"[^>]*>([^<]{0,100})', html):
    h, t = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
    blob = (t + " " + h).lower()
    if re.search(r"calendar|database|event|xii|s12|season-12", blob):
        print(f"{t[:70]} -> {h}")

print("--- text hits ---")
for pat in ["full event", "database", "Championship Qualifier", "Grandmaster Quest Events", "Upcoming"]:
    i = html.lower().find(pat.lower())
    print(pat, i)
    if i >= 0:
        snip = re.sub(r"<[^>]+>", " ", html[i : i + 500])
        print(re.sub(r"\s+", " ", snip)[:300])
