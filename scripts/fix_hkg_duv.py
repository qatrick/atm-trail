import sqlite3

c = sqlite3.connect(r"c:\Users\user\src\trail\data\grandmasters.db", timeout=60)
updates = [
    (179, "907597", "Chan, Pui-Hung (Rachel)"),
    (292, "2126417", "Choi, Ma-Yan"),
]
for rid, duv, name in updates:
    url = f"https://statistik.d-u-v.org/getresultperson.php?runner={duv}"
    c.execute(
        """
        UPDATE runners
        SET duv_runner_id=?, duv_url=?, duv_match_status=?, duv_match_score=?, duv_name=?
        WHERE id=?
        """,
        (duv, url, "manual", 999, name, rid),
    )
    print("updated", rid, name, duv)
c.commit()
for r in c.execute(
    "SELECT id,name,duv_runner_id,duv_name,duv_match_status FROM runners WHERE id IN (179,292)"
):
    print(r)
