# env_templates/

Blank BEJSON 104a schema templates for the two-file env scheme, generated
directly from the real on-device `secureenv_file.json` / `paths.json`
(2026-08-16) with every `var_value` wiped to `""` — same `var_name` /
`var_value` / `var_type` / `Flag` / `Description` fields, same `Schema_Name`
("GlobalEnv"), same rows, just no secrets in this copy. This is Elton's
actual current roster, not a guessed one — regenerate the same way (dump,
blank values, save) any time the real files' schema or roster changes so
these don't go stale again.

- `secureenv_file.template.json` — credential/secret vars (`var_type`
  `secret`). Copy to `/storage/emulated/0/.env/secure/secureenv_file.json`
  and fill in values. `Flag` on the Gemini keys marks tier (`AI_PLUS`,
  `AI_PRO`) where set — NewAgent's sync doesn't read `Flag` today, it's
  carried through untouched for forward-compat / human reference.
- `paths.template.json` — non-sensitive vars (paths, IDs, roots). Copy to
  `/storage/emulated/0/.env/user/paths.json` and fill in values.

`config/config.json`'s `env_secure_file_path` / `env_paths_file_path`
fields already point at Elton's actual on-device paths above by default --
these templates are only needed if setting up a new device, or if you want
to hand this app to someone else and they need a starting point. The
legacy single `env_file_path` field still works as a fallback if neither
new file exists (see `env_file_path`'s description in config.json).
