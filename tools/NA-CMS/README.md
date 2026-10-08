# NewAgent CMS

A personal, self-hosted CMS built on BEJSON/MFDB storage instead of SQL. Every
page, category, author, ad, nav link, and media record lives as rows inside a
single MFDB manifest (`storage/mfdb/site_master/104a.mfdb.bejson`) backed by
one BEJSON 104 entity file per table. One Flask app edits that data; a second
publisher renders it out to a static, dependency-free HTML site.

This is the **NewAgent CMS** fork of the old BEJSON CMS project — stripped
down to just the two apps that matter day to day (Admin + Publisher). Page
Editor V1/V2 and the AI Persona Hub (Profile Manager) have been removed
entirely; all prior logs and change history were cleared as part of the fork.

## Features

- **Admin app** (`NewAgent_CMS_Admin.py`) — pages, categories, media
  library, standalone apps, authors, nav/social/ad config, HTML import, and a
  publish trigger, split into four Blueprints (System / Content / Media /
  Interface) registered from one thin entry point.
- **Canonical Prefix Taxonomy & Strategy Renderers** — all live entity tables
  use canonical prefix tags (`page_`, `author_`, `asset_`, `extmedia_`, `ad_`,
  `cat_`, `nav_`, `sys_`, `social_`, `app_`) and synthetic UUID primary keys
  (`<prefix>_uuid`). Static rendering uses a polymorphic strategy pattern
  (`NewAgent_CMS_Renderers.py`) for Standard, Video, and Document page types.
- **Static publisher** (`NewAgent_CMS_Publisher.py`) — renders the full MFDB
  content set into `storage/builds/` as a static site (dark/light themes,
  category/page/app feeds, ad zones, generated excerpts, polymorphic page
  type rendering).
- **Single-service launcher** (`cms_launcher.sh`) — kills any other running
  CMS service before starting the requested one, keeping RAM usage low on
  constrained devices (Termux/Pydroid3 on Android). Two services now: Admin
  and Publisher.
- **MediaAsset-backed Media Library** — paginated gallery, hash-dedup upload
  queue (single serial worker, low peak memory), bulk delete, replace,
  external-media links, tap-to-zoom lightbox.
- **`newagent-manage.py`** — a full headless CLI for every entity (pages,
  authors, categories, nav links, ads, assets, apps, config), plus
  backup/restore and factory-reset. See `docs/CLI_GUIDE.md`.

## Removed in this fork

- `NewAgent_CMS_PageEditor.py` / `NewAgent_CMS_PageEditorV2.py` (both page
  editor generations)
- `NewAgent_CMS_ProfileManager.py` (AI Persona Hub / `AI_Profile` records)
- `lib_cms_persona_writer.py`, `lib_mfdb_chunker_v6.py`, `src/lib/cli/*`
  (book-builder / ebook / showcase tooling), taxonomy audit/migrate scripts
- All prior `CHANGELOG.md` history, `storage/logs/`, `storage/tmp/logs/`,
  and the old `.bejson_project.json` change log (this fork starts its own
  tracker — see `.bejson_project.json`)

## Installation

```bash
# Python 3.10+, Flask required. No other services (no SQL server) needed.
pip install flask --break-system-packages
```

No build step — this is a flat Python/Flask project. Clone or unzip it
anywhere; every script self-locates its own root via `SCRIPT_PATH`.

## Usage

Start the admin app (recommended entry point on Android/Termux):

```bash
python3 pydroid_start.py
# → launches src/web/NewAgent_CMS_Admin.py on http://127.0.0.1:5001
```

Or launch either service directly through the modular launcher, which
ensures only one Flask process runs at a time:

```bash
./cms_launcher.sh
# 1) Admin (Dashboard)              :5001
# 2) Static Site Publisher          :5001
# 4) Advanced Launcher (run both at once, PID-tracked)
```

Manage content headlessly (no Flask server required) with `newagent-manage.py`
— see `docs/CLI_GUIDE.md` for the full command reference:

```bash
python3 src/newagent-manage.py status
python3 src/newagent-manage.py page list
python3 src/newagent-manage.py page add "New Post" --category NewAgent --body body.html
```

Publish the live database to a static site:

```
Open NewAgent_CMS_Publisher.py's web UI (Interface > Publish) and click Build,
or POST to its /build route. Output lands in storage/builds/.
```

Set `CMS_PASSWORD` before exposing any service beyond localhost — it defaults
to `changeme` and prints a loud startup warning if left unset.

## Project Structure

```
src/web/             Two Flask apps: Admin (+ its 4 Blueprints) and Publisher
../../lib/           Shared Core libraries (from NewAgent's top level)
../../tools_lib/na-cms/  CMS-specific libraries (CMSCore, cms_mfdb, etc.)
storage/mfdb/         Live database: site_master manifest + entity files,
                     pages_db/ (per-page content), assets/, standalone_apps/
storage/builds/       Generated static site output (regenerated on publish)
storage/tmp/          Import staging (wiped on factory reset)
resources/            HTML skeleton templates + dark/light stylesheets +
                     seeded default brand assets
docs/                 CLI guide + architecture notes
tests/                pytest suite (path guard + MFDB validator coverage)
```

## License

This project is licensed under PolyForm Noncommercial 1.0.0 — free for
personal, educational, research, and non-commercial use. Commercial use
requires a separate agreement with the copyright holder. See `LICENSE`.

---
Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
