# SY OS

Production system for a knitwear export factory: buyer PO → fabric → trims → cutting → sewing → packed carton.
Django 5.2 + PostgreSQL. English, हिन्दी, தமிழ்.

**Status:** client demo. Milestone 1 (master order sheet + fabric planning) works end to end.
Milestones 2–4 are clickable previews under *Preview* in the top bar — nothing on those screens saves yet.

## Run it

```sh
brew install postgresql@17 && brew services start postgresql@17
createdb sy_os
uv sync
uv run python manage.py migrate
uv run python manage.py compilemessages
uv run python manage.py seed_demo      # demo users + sample orders, dates relative to today
uv run python manage.py runserver
```

Logins: `admin / admin123` (owner, sees costing) · `entry / entry123` (data entry) · `fabric / fabric123` (fabric in-charge).
Master data (buyers, parties) and read-only history: `/admin/`.

Tests: `uv run python manage.py test core`

## Rules built in
- Costing is admin-only, enforced in the view (403), not just hidden.
- Every record stores who, when and source (`manual` / `scan` / `device`) so scanners and scales fill the same fields later.
- No hard deletes in the app. Quantity changes after first entry need a reason and are logged as amendments.
- Fabric window per colour × dia line: in-house + lots expected by cut-start vs need → on track / late (kg gap) / short planned (kg to book).

Hindi and Tamil text is a first machine-assisted pass; the floor team must check terms before go-live.
