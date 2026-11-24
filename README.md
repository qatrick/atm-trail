# ATM Grandmasters

Local browse UI for the [Asia Trail Master Grandmaster Database](https://www.asiatrailmaster.com/grandmaster-database).

## Setup

```bash
pip install -r requirements.txt
python scripts/load_db.py
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000

## Cloudflare Pages (static mock)

Exports SQLite → JSON and deploys a static site (client-side filters; no FastAPI on CF).

```bash
python scripts/export_cf_pages.py
npx wrangler pages deploy cf-dist --project-name atm-trail
```
