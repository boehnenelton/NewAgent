---
name: anti-fluff-auditor
description: Audit and eradicate marketing buzzwords, slogans, metaphor leaks, and implementation bragging per §2.7 & §3.7 (Core Purpose Labeling Law). Use when inspecting UI titles, page headers, export artifacts, and code for fluff or hype. Do NOT use for AST field map cache audits (use policy-bejson-auditor), policy conflict audits (use policy-conflict-auditor), or credential leak audits (use policy-secrets-leak-auditor).
---

# anti-fluff-auditor (Layer 2 Core Purpose Labeling & Anti-Fluff Gate)

- **Target Architecture**: Android Termux (aarch64 / ARM 64-bit, Android Bionic libc) & Linux
- **Architectural Tier**: Layer 2 (L2) Verification & Validation Gate
- **Author Credit**: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
- **RELATIONAL_ID**: `b3e8c71a-4d2f-4a89-9e10-c5b6a7d8e9f0`
- **Version**: `101`
- **Policy Grounding**: Policy §2.7 & §3.7 (Core Purpose Labeling Law & Negative Constraints)
- **Downstream Collaborator**: `pre_tool_use_guardrail.py`, `project-delivery-packager`

---

## 1. When to Use & When NOT to Use

### Use This Skill When:
- Auditing UI templates, HTML titles, terminal menus, page headers, badges, button labels, and export artifacts for buzzword fluff, slogans, and marketing hype.
- Eradicating architectural metaphor leaks (e.g. "Chamber Web", "[CHAMBER: ...]", "Loaded Chamber", "Unload") that bleed internal design patterns into user-facing interfaces.
- Eliminating implementation bragging (e.g. "Zero-SQL Categorized Notes Hub", "High-Density NoSQL", "AI-Native") where internal backend architecture is plastered onto public labels.
- Running pre-delivery verification scans on web apps, CLI tools, and export artifacts before packaging or deployment.
- Verifying that every user-facing label answers strictly: **"What is its plain, functional core purpose?"**

### When NOT to Use:
- Do NOT use for BEJSON AST field map cache and naming audits (use `policy-bejson-auditor`).
- Do NOT use for unmasked API key or secret leakage audits (use `policy-secrets-leak-auditor`).
- Do NOT use for policy document contradiction audits (use `policy-conflict-auditor`).
- Do NOT use for adversarial API endpoint reviews (use `audit-adversarial-reviewer`).
- Do NOT use for packaging releases (use `project-delivery-packager`).

---

## 2. The Core Purpose Labeling Law (§2.7 & §3.7)

> [!IMPORTANT]
> **Core Axiom**: Never brand, slogan, or create marketing hype instead of labeling a tool, feature, or UI component by its plain, functional core purpose. Do not brand the user's software.

### The Two Primary Violation Archetypes

#### Archetype 1: Architectural Metaphor Leaks
Internal design patterns, state-machine metaphors, or engineering jargon must **never** leak into user-facing titles, navigation, badges, or buttons.
- ❌ **Prohibited**: `"Chamber Web"`, `"Loaded Chamber UI"`, `"[CHAMBER: not_002]"`, `"(chamber unloaded)"`, `"Unload Note"`
- ✅ **Required**: `"Notes Editor"`, `"Notes Management Console"`, `"[Active: not_002] Note Title"`, `"(No note selected)"`, `"Close Note"`
- **Rationale**: The user is editing a note, not firing a firearm or operating an internal CLI stage-machine chamber.

#### Archetype 2: Implementation Flexing & Technical Bragging
Users and downstream consumers do not care about internal database paradigms or architectural optimizations on surface labels. Bragging about implementation choices on titles and export headers is strictly prohibited.
- ❌ **Prohibited**: `"Zero-SQL Categorized Notes Hub"`, `"High-Density NoSQL Store"`, `"O(1) Cached Data Engine"`, `"AI-Native Notes"`
- ✅ **Required**: `"Notes Hub"`, `"Notes Database"`, `"Data Store"`, `"Notes"`
- **Rationale**: "Notes Hub" is completely sufficient. Nobody cares that the note editor is NoSQL or Zero-SQL.

#### Archetype 3: Over-Descriptive Category Fluff & Puffery
Category sections and page headings must never use inflated, grandiose titles or puffery subtitles.
- ❌ **Prohibited**: `"Knowledge Hub / Authoritative technical notes"`, `"Architecture & Technical Knowledge Hub"`
- ✅ **Required**: `"Notes - Architecture"`, `"Notes - General"`, `"Notes - Specs"`
- **Rationale & Definition of Purpose-Driven**: "Purpose-driven" means the label strictly describes the functional entity and its concrete purpose (what it literally is or does). When an element serves as a category of notes, its purpose-driven name or label is `Notes - (Category Name)`.

---

## 3. Negative Constraints Taxonomy

| Category | Banned Fluff / Slogan | Why Prohibited | Required Functional Replacement |
| :--- | :--- | :--- | :--- |
| **Category Fluff** | `Knowledge Hub`, `Technical Knowledge Hub` | Over-descriptive fluff violating purpose-driven labeling | `Notes - (Category Name)` (e.g. `Notes - Architecture`) |
| **Puffery Subtitle** | `Authoritative technical notes...` | Grandiose puffery in place of literal purpose | Omit subtitle or state literal contents |
| **Metaphor Leak** | `Chamber Web`, `Loaded Chamber` | Internal CLI metaphor leaks to UI | `Notes Editor`, `Notes Tool` |
| **Metaphor Leak** | `[CHAMBER: <id>]` | Mechanical jargon in status badge | `[Active: <id>]` or `<title>` |
| **Metaphor Leak** | `(chamber unloaded)` | Metaphor leaks into empty state | `(No note selected)` |
| **Metaphor Leak** | `Unload Note` / `Unload` | Metaphor leaks into action button | `Close Note` / `Deselect` |
| **Implementation Flex** | `Zero-SQL Categorized Notes Hub` | Public bragging about storage tech | `Notes Hub` |
| **Implementation Flex** | `Zero-SQL <X>` / `NoSQL <X>` | Unsolicited architecture flex | `<X>` (e.g. `Notes Editor`, `Portal`) |
| **Implementation Flex** | `High-Density NoSQL` | Technical flex in public title | `Database` or `Store` |
| **Sloganeering** | `Data God Edition` | Pretentious self-aggrandizing hype | Use version integer: `v1.5.0` |
| **Marketing Hype** | `Vanguard of compute` | Grandiose marketing puffery | Remove phrase; state direct facts |
| **Marketing Hype** | `Revolutionary <X>` | Unverifiable hype adjective | `Decoupled <X>`, `Modular <X>` |
| **Marketing Hype** | `World-class <X>` | Unsolicited marketing slogan | State functional purpose directly |
| **Marketing Hype** | `Game-changer` / `Battle-hardened`| Cliché buzzword fluff | State verified test status: `Stable` |
| **Header Clutter** | Multi-link navbars inside top header row | Clutters header; violates purpose-driven layout | `[Hamburger] [Title <= 3 words] [Settings]` |

---

## 4. Automation & Verification Tooling

### CLI Audit Tool: `scripts/fluff_auditor.py`
Run automated recursive scans across codebases, HTML templates, and export files:
```bash
# Scan a directory recursively:
python3 scripts/fluff_auditor.py /path/to/target

# Enforce strict exit code in CI/CD or quality gates (Exit 0 = Clean, Exit 1 = Violations):
python3 scripts/fluff_auditor.py /storage/emulated/0/Admin/System/tools/management_tool
```

### Layer 3 Lifecycle Hook: `anti_fluff_guard.py`
Integrated directly into `pre_tool_use_guardrail.py` and `hooks.json`. Automatically blocks any `write_to_file` or `replace_file_content` call containing prohibited fluff, returning:
```json
{
  "decision": "deny",
  "reason": "Core Purpose Labeling Violation (Policy §2.7 & §3.7): Offending token: 'Zero-SQL Categorized Notes Hub'..."
}
```

---

## Universal Architectural Audit & Quality Invariants

All auditing and verification routines in this skill must enforce the universal architectural principles documented in [`principals_of_design.md`](file:///storage/emulated/0/Admin/Resources/Reports/principals_of_design.md) and the 10 critical anti-patterns detailed in [`bad_design.md`](file:///storage/emulated/0/Admin/Resources/Reports/bad_design.md):

1. **Concurrency & Thread-Safety Audit**:
   - Audit codebases for shared mutable module globals.
   - Enforce Two-Tier PathLocking (`TwoTierPathLock`: per-path thread lock + cross-process `ResilientPIDLock`) on all persistent file writes.
   - Verify that file updates use atomic write-temp-and-rename (`os.replace`) rather than unsafe in-place truncation (`open(..., 'w')`).
2. **O(1) Field Map Caching Audit**:
   - Mandatory AST check: Flag and reject any numeric column offsets ($0, 1, 2$) used to index tabular rows. All column lookups must resolve via compiled `_bejson_field_map` dictionaries.
3. **Security, Auth & Session Audit**:
   - Flag and reject plaintext credentials, weak fallbacks (`admin:changeme`), and missing password hashing (Argon2id/Bcrypt).
   - Verify CSRF protection tokens on all mutating HTTP routes (`POST`, `PUT`, `DELETE`).
   - Audit file upload routines for extension whitelisting, MIME checks, and randomized UUID filenames.
4. **Presentation & Separation of Concerns Audit**:
   - Flag monolithic HTML/CSS/JS strings concatenated inside Python route controllers; enforce Jinja2 template inheritance with auto-escaping.
5. **Zero `print()` Production Logging Audit (Policy §2.2)**:
   - Mandatory AST check: Strictly zero `print()` statements in production libraries; all diagnostics must use `logging.getLogger(...)`.
   - Flag bare `except Exception: pass` blocks that swallow database corruption or filesystem write errors.
6. **Deprecation & Code Hygiene Audit**:
   - Audit against deprecated modules living in active import paths (e.g. `BEJSON_CMS_PageEditorV2.py`); verify physical quarantine into `archive/` or `dev/deprecated/` with runtime warning barriers.
7. **Environment Governance Audit (Policy §4.5)**:
   - Verify environment paths resolve dynamically via `$DEFINITIONS_FILE` (`/storage/emulated/0/.env/user/definitions.json`); flag hardcoded paths and deprecated `paths.json`.
8. **Core Purpose Labeling & Anti-Fluff Audit (Policy §3.7)**:
   - Eradicate marketing buzzwords ("Data God", "revolutionary"), architectural metaphors ("Chamber", "War Room"), and implementation flexing ("Zero-SQL", "O(1)") from user-facing surfaces.

