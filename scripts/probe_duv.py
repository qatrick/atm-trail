import re
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; ATM-Grandmaster-Archive/1.0)"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


q = urllib.parse.urlencode({"sname": "Kitamura, Hisashi", "language": "EN"})
html = fetch("https://statistik.d-u-v.org/searchrunner.php?" + q)
print("len", len(html))

# Find all runner links with surrounding row
for m in re.finditer(
    r'getresultperson\.php\?runner=(\d+)[^>]*>\s*([^<]+?)\s*</a>(.*?)</tr>',
    html,
    re.I | re.S,
):
    rid, name, rest = m.group(1), m.group(2), re.sub(r"<[^>]+>", " | ", m.group(3))
    rest = re.sub(r"\s+", " ", rest)
    print(rid, name, "|", rest[:300])

print("--- bulk page ---")
bulk = fetch("https://statistik.d-u-v.org/bulksearch.php")
print(bulk[:1500])
