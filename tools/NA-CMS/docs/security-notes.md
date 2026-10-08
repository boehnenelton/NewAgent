# Security & Architecture Notes

Current-state notes on real structural gaps in this fork — not a change
history (see `.bejson_project.json` for the fork's own changelog going
forward).

---

## `newagent-manage.py`'s two data-access layers

`newagent-manage.py` exposes two different ways to reach BEJSON/MFDB data:

- **`get_manager()`** → `MFDB_CMS_Manager` (`lib_bejson_NewAgentCMS_cms_mfdb.py`) —
  operates on a disconnected workspace/archive model
  (`storage/workspace/db_global/`, `storage/workspace/db_content/`),
  populated only by extracting archive zips via `mount_system()`. No such
  archives ship with this project, so `mount`/`commit` bootstrap an empty
  workspace rather than touching real data. Only `status`, `mount`, and
  `commit` still use this path, and both `mount`/`commit` print an explicit
  warning before running. Use `backup`/`restore` for real live-data
  snapshots instead.
- **`get_db()`** → `CMSCore` (`lib_bejson_NewAgentCMS_cms_core.py`) — the
  same manifest the Admin and Publisher Flask apps read/write
  (`storage/mfdb/site_master/104a.mfdb.bejson`). Every data command —
  `page`, `author`, `category`, `navlink`, `ad`, `asset`, `app`, `config`,
  `backup`, `restore` — uses this path and is confirmed live-data-accurate.

**Practical rule:** if a command isn't `mount`, `commit`, or the "Mounted"
line printed by `status`, it's touching the real, live site data.

## `page` write contract

A page write is two parts, both required: a `PageRecord` row via `CMSCore`
(field-map-cache lookups, no positional indexing) plus a standalone
`pages_db/<uuid>.json` 104db content file, written atomically
(temp file + `os.replace`). `newagent-manage.py`'s `page add`/`update`/
`delete`/`import` commands implement both halves; anything hand-rolling a
page write outside `CMSCore` risks producing one half without the other
(a 404 or a permanently-empty page).

## Known remaining gap

`asset optimize`'s live write shape (PNG→WebP conversion path) has not been
independently re-verified against `CMSCore` in this fork. Treat it as
unverified until confirmed with a real before/after `db list assets` check.

---

*Add new entries above this line. State what was actually run/observed to
confirm a finding, not just what the code appears to do on read-through.*
