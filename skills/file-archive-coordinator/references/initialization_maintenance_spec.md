# Initialization Maintenance & Project Archive Retention Specification

* System: Layer 6 Workflow & Maintenance
* Policy Grounding: GEMINI.md — Initialization Maintenance (§1.1, §3.1)
* Component: `file-archive-coordinator`
* CLI Tool: `scripts/project_archive_janitor.py`
* Author: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
* Date Created: 2026-10-22

---

## 1. Operational Gap & Architectural Rationale

Session initialization mandates sweeping `/storage/emulated/0/Download/` for package files or directories matching the solid integer version pattern:
$$\texttt{(PROJECT\_NAME)-(VERSION)-(PKGVERSION)}$$

Previously handled by ad-hoc bash loops, this process risked:
1. Deleting the latest active build due to ambiguous version string comparison.
2. Leaving loose uncompressed directories across shared storage.
3. Overwriting distinct archive builds when identical filenames arrived without collision resolution.
4. Hardcoding absolute storage paths instead of resolving canonical environment variables via `paths.json`.

`file-archive-coordinator` automates this lifecycle deterministically via `project_archive_janitor.py`.

---

## 2. Package Grammar & Regex Specification

Matching regular expression:
```regex
^(?P<project_name>[A-Za-z0-9_]+)-V(?P<version>[0-9_]+)-PKG(?P<pkg_version>[0-9_]+)(?:-(?P<build>[0-9_]+))?(?P<archive_ext>\.zip)?$
```

### Supported Match Exemplars:
- `Autobase64-V8-PKG100-1.zip` (Project: `Autobase64`, Version: `8`, PKG: `100`, Build: `1`)
- `Autobase64-V8-PKG100.zip` (Project: `Autobase64`, Version: `8`, PKG: `100`, Build: `0`)
- `Autobase64-V9-PKG100.zip` (Project: `Autobase64`, Version: `9`, PKG: `100`, Build: `0`)
- `CLI_AI-V2134-PKG35.zip` (Project: `CLI_AI`, Version: `2134`, PKG: `35`)
- `BookWriter-V1_0_1-PKG101.zip` (Project: `BookWriter`, Version: `(1, 0, 1)`, PKG: `101`)
- `Experimental_CMS-V3110-PKG31` (Loose directory matching pattern: compressed to ZIP before movement)

---

## 3. Retention Enforcement Protocol

For each identified project family:
1. **Loose Directory Compression**: Any uncompressed directory matching the package pattern is zipped to `<dirname>.zip`. The original directory is purged only after zip integrity verification.
2. **Version Sorting**: Packages are ordered ascending by `(version_tuple, package_tuple, build_number, mtime)`.
3. **Download Retention**: The **highest (latest)** version is retained in `/storage/emulated/0/Download/`.
4. **Archive Movement**: All older versions are moved into:
   ```
   /storage/emulated/0/Admin/Core/Projects_Archive/<ProjectName>/
   ```
5. **Duplicate Pruning**: If a file with identical SHA-256 checksum already resides in the project archive, the redundant file in Download is safely deleted. If timestamps or checksums differ, microsecond disambiguation suffixes are applied to prevent collision data loss.
