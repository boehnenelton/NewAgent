# Architecture

## Components

**NewAgent_CMS_Admin.py** — the registered Flask entry point. Imports and
registers four Blueprints with no URL prefix (routes are flat/absolute, e.g.
`/pages`, not `/content/pages`), plus a global `before_request` auth hook so
every admin route requires authentication.

- **System cube** (`NewAgent_CMS_System.py`) — dashboard stats, `SiteConfig`
  key/value editing, factory reset (`/reset`, `/reset/confirm`), the
  `_ensure_uncategorized_category()` and `_seed_default_brand_and_author()`
  self-heal routines that run on every startup so a permanent
  `Uncategorized` category and a default author/brand-asset set survive even
  a full wipe.
- **Content cube** (`NewAgent_CMS_Content.py`) — `PageRecord` CRUD + duplicate,
  `Category` CRUD, `StandaloneApp` CRUD (ZIP-extract with a 300MB
  uncompressed-size guard checked from the ZIP's central directory, no
  decompression needed), `AuthorProfile` CRUD, and the HTML-import pipeline
  (preview → confirm → per-item processing via `/api/import/process_item`).
- **Media cube** (`NewAgent_CMS_Media.py`) — `MediaAsset`/`ExternalMedia` CRUD.
  Uploads stream straight to disk, then a job dict is queued; a single serial
  background worker (`_asset_worker`) does hashing/dedup/DB-registration/
  thumbnailing one file at a time, sleeping and calling `gc.collect()`
  between jobs to bound peak memory on constrained hardware.
- **Interface cube** (`NewAgent_CMS_Interface.py`) — the CMS's own home page,
  `NavLink`/`SocialLink`/`AdUnit` config, and the `/publish` trigger that
  hands off to `NewAgent_CMS_Publisher.py`.

**NewAgent_CMS_Publisher.py** is the static-site generator. It reads every
entity through `CMSCore`, dispatches page body rendering to polymorphic
strategy renderers (`NewAgent_CMS_Renderers.py` — supporting
`StandardPageRenderer`, `VideoPageRenderer`, `DocumentPageRenderer`), renders
the `resources/templates/*.html` skeletons, generates per-page excerpts
(`_generate_excerpt()` — falls back to a 30-word plain-text excerpt when no
meta description is set), filters ad units by `ad_zone`, and writes the
complete output to `storage/builds/` (`index.html`, `style.css`,
`category/<slug>/`, `page/<category>/<slug>/`, `apps/`, `assets/`).

> **Fork note:** the old BEJSON CMS project also shipped Page Editor V1/V2
> (standalone form/API-driven editors) and an AI Persona Hub / Profile
> Manager (`AI_Profile` records feeding AI-assisted page generation). Both
> were removed in the NewAgent CMS fork — page content is now edited
> through the Content cube of the Admin app only, and there is no AI-persona
> layer.

## Canonical Naming Taxonomy

All live database entities use a consistent snake_case field-prefix
convention plus a synthetic UUID primary key at position 0:

| Entity | Prefix | Fields |
|---|---|---|
| `PageRecord` | `page_` | `page_uuid`, `page_title`, `page_slug`, `page_cat_name`, `page_type`, `page_author_name`, `page_featured_img`, `page_created_at`, `page_external_url` |
| `AuthorProfile` | `author_` | `author_uuid`, `author_display_name`, `author_bio`, `author_avatar_url` |
| `MediaAsset` | `asset_` | `asset_uuid`, `asset_filename`, `asset_original_name`, `asset_file_hash`, `asset_file_size`, `asset_mime_type`, `asset_uploaded_at` |
| `ExternalMedia` | `extmedia_` | `extmedia_uuid`, `extmedia_name`, `extmedia_type`, `extmedia_url`, `extmedia_created_at` |
| `Category` | `cat_` | `cat_uuid`, `cat_name`, `cat_slug` |
| `AdUnit` | `ad_` | `ad_uuid`, `ad_name`, `ad_banner_url`, `ad_target_url`, `ad_zone`, `ad_active` |
| `NavLink` | `nav_` | `nav_uuid`, `nav_display_label`, `nav_target_url` |
| `SiteConfig` | `sys_` | `sys_uuid`, `sys_key`, `sys_value` |
| `SocialLink` | `social_` | `social_uuid`, `social_platform_name`, `social_target_url` |
| `StandaloneApp` | `app_` | `app_uuid`, `app_name`, `app_slug`, `app_description`, `app_entry_file`, `app_featured_img` |

This table is the single source of truth for field names in this fork —
there is no separate taxonomy module; application code always resolves
fields by name through `CMSCore`'s field-map cache, never by position.

## Data Flow

```
Browser (admin UI)
     │  form POST / fetch
     ▼
Blueprint route (System/Content/Media/Interface)
     │  db.add_record() / update_record() / delete_record()
     ▼
CMSCore (lib_bejson_NewAgentCMS_cms_core.py)
     │  mfdb_core_add_entity_record() / update_entity_record_bulk()
     ▼
lib_bejson_Core_mfdb_core.py
     │  per-manifest RLock → atomic write (.tmp → fsync → os.replace)
     ▼
storage/mfdb/site_master/104a.mfdb.bejson (manifest)
storage/mfdb/site_master/data/<entity>.bejson (entity file)
```

Page bodies follow a parallel, separate path: `PageRecord` metadata goes
through the flow above, while the actual `html_body` is read/written
directly as a standalone 104db document at
`storage/mfdb/pages_db/<page_uuid>.json` — Flask reads it by UUID at request
time, it is never registered as a CMSCore "entity."

Publishing is a one-way read: `NewAgent_CMS_Publisher.py` reads the live MFDB
tree (never writes back to it) and renders `storage/builds/` from scratch,
combined with the shared stylesheets in `resources/styles/`.

Media upload is asynchronous within a single request/process: the HTTP
request only streams the file to disk and enqueues a job; the actual
hash/dedup/DB-write/thumbnail work happens on the `_asset_worker` background
thread, decoupled from the request so a slow decode can't hang the whole
app.
