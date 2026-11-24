import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


html = fetch("https://m.racetimingsolutions.com/rankings")
print("len", len(html))
print("title", re.search(r"<title>(.*?)</title>", html, re.I | re.S).group(1))
links = sorted(set(re.findall(r'href=["\']([^"\']+)["\']', html)))
for l in links:
    if re.search(r"profile|rank|season|year|result|search|filter|export", l, re.I):
        print("L", l)
ids = re.findall(r"profile\?id=(\d+)", html)
print("ids", len(ids), ids[:15])
