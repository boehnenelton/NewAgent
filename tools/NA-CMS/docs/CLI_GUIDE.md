# NewAgent CMS — CLI Guide (`newagent-manage.py`)

Headless management of the live NewAgent CMS database — no Flask server
needs to be running. Every command below reads/writes the same live
manifest the Admin and Publisher web apps use
(`storage/mfdb/site_master/104a.mfdb.bejson`), with the sole exceptions
noted under **Legacy commands** at the end of this guide.

## Setup

```bash
cd tools/NewAgent_CMS   # or wherever this project root lives
python3 src/newagent-manage.py --version
python3 src/newagent-manage.py --help
```

By default the CLI operates on `<project_root>/storage`. Point it at a
different data root (e.g. a copy, for testing) with:

```bash
export CMS_DATA_ROOT=/path/to/alternate/storage
```

Every command below assumes you're running `python3 src/newagent-manage.py <command> ...`
from the project root; shorten it to `newagent-manage` in your own aliasing
if you like.

## Quick orientation

```bash
newagent-manage status
```

Prints the data root, whether the live manifest exists, and whether there
are dirty/uncommitted changes. Run this first if anything seems off.

---

## Pages

```bash
newagent-manage page list
newagent-manage page add "My New Post" --category Uncategorized --type blog --body body.html --author "Elton Boehnen"
newagent-manage page update <uuid> "Updated Title" --body new_body.html
newagent-manage page delete <uuid>
newagent-manage page import --html article.html --title "Imported Article" --category Uncategorized --author "Elton Boehnen"
newagent-manage page import --app <app_uuid> --title "Embedded App Page"
```

- `--category` takes a category **name**, not a slug — it must match an
  existing `Category`'s name exactly. Run `category list` first if unsure.
- `--author` takes an author **name**, not a UUID — must match an existing
  `AuthorProfile` exactly. Run `author list` first if unsure.
- `--body` accepts a path to an HTML file (its contents become the page's
  `html_body`).
- Every page write updates both the `PageRecord` row in the manifest *and*
  the standalone `pages_db/<uuid>.json` content file — this command handles
  both halves for you.

## Authors

```bash
newagent-manage author list
newagent-manage author add "Jane Doe" --bio "Writes about BEJSON internals." --image https://example.com/jane.jpg
newagent-manage author update "Jane Doe" --bio "Updated bio text."
newagent-manage author delete "Jane Doe"
```

Authors are identified by **name**, not UUID — the live `AuthorProfile`
schema has no UUID field, the display name is the key.

## Categories

```bash
newagent-manage category list
newagent-manage category add "Dev Log" dev-log --desc "Development updates." --type blog
newagent-manage category update dev-log "Development Log"
newagent-manage category delete dev-log
```

Categories are identified by **slug** for update/delete, but `add` takes
both a display name and a slug.

## Navigation links

```bash
newagent-manage navlink list
newagent-manage navlink add "About" /about --order 2
newagent-manage navlink delete "About"
```

## Ad units

```bash
newagent-manage ad list
newagent-manage ad add "Sidebar Banner" https://example.com/banner.png https://example.com/click-target sidebar
newagent-manage ad update <uuid> "Sidebar Banner v2" https://example.com/banner2.png https://example.com/click-target sidebar --inactive
newagent-manage ad delete <uuid>
```

`add`/`update` argument order is: `name img link zone`. Pass `--inactive`
to create/update the unit in a disabled state.

## Media assets

```bash
newagent-manage asset list
newagent-manage asset add /path/to/photo.jpg
newagent-manage asset delete photo_abc123.webp
newagent-manage asset optimize --dry-run     # preview PNG->WebP conversions
newagent-manage asset optimize               # actually convert
```

External (off-site) media, e.g. an embedded PDF hosted elsewhere:

```bash
newagent-manage asset list-external
newagent-manage asset add-external "Whitepaper" https://example.com/whitepaper.pdf --type pdf
newagent-manage asset delete-external <media_uuid>
```

> `asset optimize`'s live write path is flagged as not independently
> re-verified in this fork — see `docs/security-notes.md`. Always run
> `--dry-run` first and check `asset list` afterward.

## Standalone apps

```bash
newagent-manage app list
newagent-manage app add "Mini Game" --desc "A small embedded app." --image https://example.com/game.png --entry index.html
newagent-manage app delete <uuid>
```

`--category` is accepted for backward compatibility but ignored (a warning
prints) — the live `StandaloneApp` schema has no category field.

## Site configuration

```bash
newagent-manage config list
newagent-manage config set site_tagline "Built on BEJSON/MFDB" --desc "Shown under the site title."
newagent-manage config delete site_tagline
```

`SiteConfig` is a free-form key/value store — `title`, `description`,
`creator`, and `base_url` are seeded by default (see `NewAgent_CMS_System.py`),
but you can set any key the Publisher's templates are wired to read.

## Skeleton templates (draft / diff / promote)

```bash
newagent-manage skeleton list
newagent-manage skeleton list --theme behtml
newagent-manage skeleton show default Home_Skeleton
newagent-manage skeleton edit default Home_Skeleton      # opens $EDITOR on a draft copy
newagent-manage skeleton diff default Home_Skeleton       # unified diff vs. what's live
newagent-manage skeleton promote default Home_Skeleton    # validates + commits + backs up + bumps version
newagent-manage skeleton discard default Home_Skeleton    # throws the draft away
newagent-manage skeleton validate                         # checks every registered skeleton's {{tag}} contract
newagent-manage skeleton validate --theme behtml           # exits 1 on any failure -- script-friendly
newagent-manage skeleton new-theme my-theme --from default  # clone a theme's skeleton set as a starting point
```

Skeleton HTML lives only on disk under `resources/templates/default/`
(or a per-theme override folder) — there is no embedded-literal source of
truth to fall out of sync with any more. A `promote` is refused, and the
live file left untouched, if the draft is missing a `{{tag}}` its
registered contract requires. A real publish runs the same validation
automatically before touching the filesystem. See `docs/SKELETON_LOADER.md`
for the full explanation and `Dynamic_Skeleton_Loader-Proposal-V1.docx`
for the design rationale.

## Raw database dump

```bash
newagent-manage db list pages
newagent-manage db list pages --filter Uncategorized     # matches page_cat_name
newagent-manage db list authors
newagent-manage db list categories
newagent-manage db list assets
newagent-manage db list apps
newagent-manage db list ads
newagent-manage db list navlinks
```

Dumps raw JSON records for any entity — useful for scripting or piping into
`jq`. `--filter` only works for `pages` (matched against `page_cat_name`).

---

## Backup & restore

```bash
newagent-manage backup                       # writes a timestamped zip to storage/backups/ (default)
newagent-manage backup --dir /path/to/somewhere
newagent-manage restore /path/to/backup.zip
```

A real live-data snapshot: `storage/mfdb/{site_master,pages_db,assets,standalone_apps}`.
`restore` automatically takes a safety backup of the current state before
overwriting anything.

## Factory reset

```bash
newagent-manage factory-reset
```

**Destructive.** Wipes the live database back to its seeded defaults
(`Uncategorized` category, default brand/author, empty content). Prefer the
Admin web UI's `/reset` → `/reset/confirm` flow if you want a confirmation
step; this CLI command does not prompt.

## Running a service

```bash
newagent-manage serve admin        # same as: python3 src/web/NewAgent_CMS_Admin.py
newagent-manage serve publisher    # same as: python3 src/web/NewAgent_CMS_Publisher.py
```

Blocks in the foreground until `Ctrl+C`. For running both at once, use
`./cms_launcher.sh` (option 4, Advanced Launcher) instead — it tracks each
service by PID so they can be managed independently.

---

## Legacy commands (do not touch live data)

```bash
newagent-manage mount --force
newagent-manage commit
```

These operate on an old, disconnected workspace/archive model
(`storage/workspace/`) that has no bearing on the real site. No archive
files ship with this project, so `mount` just bootstraps an empty
workspace. `commit` is a documented no-op. **Use `backup`/`restore` instead**
for anything involving real data — see `docs/security-notes.md` for the
full explanation.

---
Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
