import sqlite3

c = sqlite3.connect(r"c:\Users\user\src\trail\data\grandmasters.db")
c.row_factory = sqlite3.Row

print("=== HKG runners ===")
for r in c.execute(
    "SELECT id,name,gender,stars,duv_runner_id,duv_name,duv_match_status FROM runners WHERE country='HKG' ORDER BY name"
):
    print(dict(r))

print("\n=== name hits Chan/Choi/Rachel/Pui/Ma-Yan ===")
for r in c.execute(
    """
    SELECT id,name,country,gender,stars,duv_runner_id,duv_name,duv_match_status
    FROM runners
    WHERE name LIKE '%Chan%' OR name LIKE '%Choi%' OR name LIKE '%Rachel%'
       OR name LIKE '%Pui%' OR name LIKE '%Ma Yan%' OR name LIKE '%Mayan%'
       OR name LIKE '%Ma-Yan%'
    ORDER BY name
    """
):
    print(dict(r))
