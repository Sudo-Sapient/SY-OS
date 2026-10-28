# SY OS

Production system for a knitwear export factory: buyer PO → fabric → trims → cutting → sewing → checking → packed carton.
Built by Sudo Sapient. Django 5.2 · PostgreSQL · English, हिन्दी, தமிழ் · works on desktop and phone.

## What it does

| Area | Screens | Rules that are enforced |
| --- | --- | --- |
| Orders (M1) | orders list, master order sheet, quantities & consumption, dia program & trims, costing, repeat | costing is admin-only on the server (403); quantity or consumption changes after first entry need a reason and are logged |
| Fabric (M1) | fabric planning per colour × dia line, lots by stage, WhatsApp follow-ups | on track / late (kg gap) / short planned (kg to book) against the cut-start date |
| Trims (M2) | calculator, raise POs per supplier, PO receipts | required = qty × per piece × (1 + wastage %), rounded up; size-wise lines where needed |
| Cutting (M3) | cut lots, new cut lot, fabric flags, fabric in hand | wrong colour/dia roll blocked; GSM ±5% and width −0.5″ need confirmation; consumption beyond ±10% blocked; bundle numbers never overlap; a lot never goes below zero kg |
| Floor (M4) | hourly sewing grid, checking & packing, size-wise tracker, dashboard | checking ≤ sewn, packing ≤ passed; alerts from rules |

Every record stores who, when and **source** (`manual` / `scan` / `device`), so scanners and scales can fill the same fields later.
Nothing is hard-deleted from the app.

## Run it locally

```sh
brew install postgresql@17 && brew services start postgresql@17
createdb sy_os
uv sync
uv run python manage.py migrate
uv run python manage.py seed_demo        # demo users + two sample orders with a day of floor data (dates relative to today)
uv run python manage.py runserver 4000
```

Logins: `admin / admin123` (owner, sees costing) · `entry / entry123` (data entry) · `fabric / fabric123` · `cutting / cutting123`.
Master data (buyers, parties, lines) and read-only history: `/admin/`.

Checks before you push:

```sh
uv run python manage.py test core       # 13 tests: fabric window, costing, amendments, cutting, checking/packing, trims POs
uvx ruff check . && uvx ruff format .   # lint + format (config in pyproject.toml)
```

## Code map

```
syos/                 project: settings.py (all env-driven), urls.py, wsgi.py
core/
  models.py           every table + the calculations: fabric_window(), tracker(), lot_balance(), consumption_status()
  permissions.py      roles (Admin, Data entry, Fabric in-charge, Cutting in-charge, Supervisor) and @roles / can_post
  forms.py            all forms; TidyForm gives dropdowns a translated "Select…"
  views/orders.py     Milestone 1: orders, master sheet, grid, setup, costing, repeat, fabric planning
  views/floor.py      Milestones 2–4: trims, cutting, sewing, checking & packing, dashboard
  templates/core/     one template per screen; partials start with "_"
  static/core/        app.css (one stylesheet, contents list at the top), sticker.js (login animation, built)
  management/commands/seed_demo.py   demo data
  tests.py
locale/hi, locale/ta  translations (.po edited by hand, .mo compiled and committed)
stickers/             source of the login sticker (fun-isometric kit); rebuild sticker.js with Bun:
                      bun build stickers/login.ts --minify --target browser --outfile core/static/core/sticker.js
docs/                 proposal, screenshots
```

Conventions: keep business rules in `models.py` or the view that saves, never in templates. New strings go through
`gettext` / `{% translate %}`; run `uv run python manage.py makemessages -l hi -l ta` and fill both `.po` files, then
`compilemessages`. Colours and radii live in the `:root` tokens at the top of `app.css`.

## Deploy

**Vercel (demo / hosted)** — zero-config Django on the Python runtime, entrypoint `syos/wsgi.py`, static files served
by WhiteNoise. Set environment variables from `.env.example`:

- `DJANGO_SECRET_KEY` — long random string
- `DATABASE_URL` — pooled Postgres URL (Neon via the Vercel Marketplace)

Run migrations and the demo seed once against that database from your machine:

```sh
DATABASE_URL='postgres://…' uv run python manage.py migrate
DATABASE_URL='postgres://…' uv run python manage.py seed_demo
```

**Factory server (the brief's target)** — same code on a machine inside the factory: Postgres locally, `gunicorn syos.wsgi`
behind nginx or Caddy, nightly `pg_dump` encrypted to the cloud. Set `DJANGO_ALLOWED_HOSTS` to the server's LAN name and,
if served over HTTPS, enable HSTS. Fonts currently load from Google Fonts; self-host them for a fully offline floor.

Hindi and Tamil text is a first machine-assisted pass — the floor team must check the terms before go-live.
