# Banned Fluff Patterns & Core Purpose Labeling Taxonomy

## Overview
This reference specifies the banned buzzword fluff, slogans, metaphor leaks, and implementation flexing prohibited under **Policy §2.7 & §3.7**.

---

## 1. Primary Violation Archetypes

### Archetype 1: Architectural Metaphor Leaks (The "Chamber Web" Anti-Pattern)
- **Violation Origin**: An internal engineering concept (such as a 3-phase "Loaded Chamber" state pattern in a CLI job manager) bleeding outward into user-facing web interfaces, headers, badges, or buttons.
- **Why It Fails**: Users do not care about internal design metaphors. They are editing a note, writing an article, or managing tasks. Using words like "Chamber Web", "[CHAMBER: not_002]", "(chamber unloaded)", or "Unload" is confusing, pretentious jargon.
- **Remediation**:
  | Offending Phrase | Required Functional Replacement |
  | :--- | :--- |
  | `Chamber Web` | `Notes Editor` |
  | `[CHAMBER: not_002]` | `[Active: not_002]` or simply note title |
  | `(chamber unloaded)` | `(No note selected)` |
  | `Loaded Chamber UI` | `Notes Management Console` |
  | `Unload Note` / `Unload` | `Close Note` / `Deselect` |

---

### Archetype 2: Implementation Flexing & Sloganeering (The "Zero-SQL Hub" Anti-Pattern)
- **Violation Origin**: Plastering technical implementation details or engineering brag terms onto export titles, document headers, or app names.
- **Why It Fails**: "Zero-SQL Categorized Notes Hub" on an export document is unsolicited branding and marketing hype. Downstream readers do not care that the backend is NoSQL or Zero-SQL. "Notes Hub" is completely sufficient.
- **Remediation**:
  | Offending Phrase | Required Functional Replacement |
  | :--- | :--- |
  | `Zero-SQL Categorized Notes Hub` | `Notes Hub` |
  | `Zero-SQL Notes` / `NoSQL Notes` | `Notes` or `Notes Hub` |
  | `High-Density NoSQL Database` | `Notes Database` or `Database` |
  | `O(1) Cached Data Engine` | `Data Cache` or `Engine` |
  | `AI-Native Knowledge Hub` | `Knowledge Hub` |

---

### Archetype 3: Self-Aggrandizing Hype & Puffery
- **Violation Origin**: Unsolicited marketing slogans, grandiose branding, or self-promotional rhetoric.
- **Remediation**:
  | Offending Phrase | Required Functional Replacement |
  | :--- | :--- |
  | `Data God Edition` | Remove slogan; use solid version integer `v1.5.0` |
  | `God Tier` | `Core Architecture` or `Advanced / System Tier` |
  | `Vanguard of compute` | Remove phrase; state objective technical function |
  | `Revolutionary architecture` | `Decoupled architecture` or `Modular format` |
  | `World-class tool` | State direct functional utility |
  | `Cutting-edge` | Remove puffery; state specific engineering features |
  | `Game-changer` / `Game-changing` | State verified performance metrics |
  | `Battle-hardened engine` | `Tested engine` or `Stable engine` |

---

## 2. Technical Writing, Blogging & Publication Guardrails

The Core Purpose Labeling Law applies with equal force to all written technical deliverables (blog posts, e-books, technical manuals, social media threads, documentation portals):

### A. Article Titles & Hero Banners
- **Law**: The title must state what the software, library, or technique is and what it does.
- ❌ **Prohibited**: `"Zero-SQL on Android: The Revolutionary Data God Engine"`, `"Loaded Chamber Web: Next-Gen Dev Experience"`
- ✅ **Required**: `"Flat-File Architecture on Android: Portable Stores with BEJSON 104"`, `"Notes Editor: Terminal & Web Interface for MFDB Notes"`

### B. Difficulty Classification Tiers
- **Law**: Classify engineering difficulty strictly using objective, technical tiers.
- ❌ **Prohibited**: `"God Tier"`, `"Data God"`, `"Vanguard Tier"`
- ✅ **Required**: `"Beginner"`, `"Intermediate"`, `"Advanced"`, `"Core Architecture"`

### C. Technical Social Threads & Launch Copy
- **Law**: Hook developers with verified engineering innovations, empirical benchmarks, and clean CLI quickstarts, never empty puffery.
- ❌ **Prohibited**: `"This revolutionary database is a game-changer that puts SQL to shame!"`
- ✅ **Required**: `"A flat-file tabular data format with O(1) field map caching in pure standard library Python. Here are the benchmarks and CLI walkthrough:"`

### D. Documentation & Manuals
- **Law**: Zero fluff, zero unsolicited branding, zero metaphor leaks. Document concrete API routes, exit codes, and operational contracts truthfully.
