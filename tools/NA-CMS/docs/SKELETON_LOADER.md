# Skeleton Loader

How the published site's HTML templates ("skeletons") work now, and how
to edit them safely. This replaces the old `SkeletonBuilder` pattern --
see `Dynamic_Skeleton_Loader-Proposal-V1.docx` for the full design
rationale if you want the reasoning, not just the how-to.

## What changed

Skeleton HTML used to live in two places that had to be hand-kept in
sync: Python string literals inside `NewAgent_CMS_Publisher.py`, and the
actual files under `resources/templates/`. The literals were secretly
authoritative -- a "Force Regenerate" button overwrote the files from
them. Editing a file directly, the obvious thing to do, could be silently
wiped the next time that button was clicked.

That's gone. Skeleton markup now lives **only** on disk, one canonical
copy per file, tracked by `resources/skeleton_registry.json`. There is no
code path left that can overwrite a file you've edited without going
through the draft/promote flow described below.

## Where the files are

```
resources/templates/
  default/              <- the live, canonical skeleton set (7 files)
  _factory/default/     <- frozen "factory reset" baseline, read-only in
                            practice -- only touched by 'reset-theme'
  <theme>/              <- optional per-theme override folder; only
                            needed if a theme's markup genuinely diverges
                            from default/, not just its CSS
```

Every theme (`dark.css`, `light.css`, `behtml.css`, or a new one you add)
shares `default/` unless you create a same-named folder to override
specific files. Today, no theme overrides anything -- markup is identical
across all three, only the CSS differs.

## Two ways to edit a skeleton

**Quick edit** -- for a small, low-risk change: just edit the file in
`resources/templates/default/` (or the relevant theme folder) directly.
It's live at the next publish, same as before.

**Draft/promote** -- for anything you want to preview and compare before
it goes live:

```bash
newagent-manage skeleton edit default Home_Skeleton
# opens $EDITOR on a draft copy (seeded from the current live file if
# no draft exists yet)

newagent-manage skeleton diff default Home_Skeleton
# shows a unified diff between what's live and what you just edited

newagent-manage skeleton promote default Home_Skeleton
# validates the draft against its {{tag}} contract, backs up the current
# live file to resources/templates/_history/, then commits the draft as
# live and bumps its version

newagent-manage skeleton discard default Home_Skeleton
# throws the draft away instead, if you change your mind
```

A promote is refused (the live file is untouched) if the draft is
missing a `{{tag}}` the renderer needs -- you'll see exactly which one.

## Checking everything is healthy

```bash
newagent-manage skeleton list                    # every registered skeleton, version, tag count
newagent-manage skeleton list --theme behtml      # just one theme
newagent-manage skeleton validate                 # checks every registered skeleton's tag contract
newagent-manage skeleton validate --theme behtml   # exits 1 if anything's broken -- script-friendly
```

A real publish (`/publish` in the Admin app, or the build routine
directly) runs this same validation automatically before touching the
filesystem. If any *wired-up* skeleton is missing a required tag, the
build aborts with a clear per-file error instead of shipping a broken
page.

`App_Skeleton` and `Author_Skeleton` are registered but marked
**not wired up** -- they're written to disk but the render pipeline never
actually calls `_read_skel()` for them (a pre-existing gap from before
this system existed, now at least visible instead of silently assumed to
work). They're excluded from the pre-publish gate for that reason; fixing
the gap itself is a separate task.

## Starting a new theme

```bash
newagent-manage skeleton new-theme my-theme --from default
```

Clones every registered skeleton from `--from` (default: `default`) into
a new `resources/templates/my-theme/` folder and registers matching
registry rows. Then either:

- Only some files actually need to differ from `default/` -- delete the
  ones that don't, and the loader falls back to `default/` for those
  automatically; or
- If it's meant to be a real selectable site theme (not just a markup
  variant), also add a matching `resources/styles/my-theme.css` -- it
  shows up in the Admin app's theme picker automatically (any `.css` file
  in `resources/styles/` does).

## Resetting a theme back to its shipped defaults

In the Admin app's Publisher page: **Reset Theme to Factory Default**
(under "Skeleton Files"). Copies every file from
`resources/templates/_factory/default/` onto the active theme's folder --
a plain file copy, never code -- and backs up whatever was live first.
Only ever touches the current theme's folder; other themes are
untouched.
