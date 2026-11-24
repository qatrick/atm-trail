import sqlite3

c = sqlite3.connect(r"c:\Users\user\src\trail\data\grandmasters.db")
print("with_url", c.execute("SELECT COUNT(*) FROM runners WHERE duv_url IS NOT NULL").fetchone()[0])
print("status", c.execute("SELECT duv_match_status, COUNT(*) FROM runners GROUP BY 1 ORDER BY 2 DESC").fetchall())
print(
    "no url",
    c.execute(
        "SELECT name, country FROM runners WHERE duv_url IS NULL"
    ).fetchall(),
)
