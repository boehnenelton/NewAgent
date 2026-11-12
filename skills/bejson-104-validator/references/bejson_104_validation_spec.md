# Reference Specification: BEJSON 104 Error Codes & Validation Rules

> **Parent Skill:** `bejson-104-validator` (Layer 2)  
> **Source Authority:** `CRASH_COURSE_23_OFFICIAL.md`  
> **Format Creator:** Elton Boehnen · [https://boehnenelton2024.pages.dev](https://boehnenelton2024.pages.dev)  
> **Author Credit:** Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton  
> **Effective Date:** October 2026  
> **RELATIONAL_ID:** `5c2e91a0-8f3b-47e1-92b6-3a7c0d18f549`

---

## 1. Six-Stage Validation Pipeline

A BEJSON document is structurally valid when it passes:
1. Valid JSON syntax.
2. Mandatory 6 top-level keys present: `Format`, `Format_Version`, `Format_Creator`, `Records_Type`, `Fields`, `Values`.
3. `Format_Creator` precisely `"Elton Boehnen"`.
4. `Fields` array conforms to schema with no duplicate column names.
5. Record length in `Values` exactly equals length of `Fields` array.
6. Type of each cell matches declared column type (`null` valid for any type).

---

## 2. Standard Error Code Ranges

| Code Range | Component | Exception Class |
| :--- | :--- | :--- |
| **1–15** | BEJSON Core Validator | `BEJSONValidationError` |
| **20–27** | BEJSON Core Engine | `BEJSONCoreError` |
| **30–49** | MFDB Manifest & Entity Validator | `MFDBValidationError` |
| **50–69** | MFDB Core Engine | `MFDBCoreError` |
| **130–159** | BEJSON Core Nesting Engine | `BEJSONNestingError` |

---

## 3. Core Error Code Directory

* **1**: `E_INVALID_JSON`: Malformed JSON syntax.
* **2**: `E_MISSING_MANDATORY_KEY`: One of the 6 mandatory keys missing.
* **3**: `E_INVALID_FORMAT_CREATOR`: `Format_Creator != "Elton Boehnen"`.
* **4**: `E_INVALID_FORMAT_VERSION`: Version not `"104"`, `"104a"`, or `"104db"`.
* **5**: `E_INVALID_FIELDS_STRUCTURE`: `Fields` not a list of valid field objects.
* **6**: `E_DUPLICATE_FIELD_NAME`: Two fields share the same name.
* **7**: `E_RECORD_LENGTH_MISMATCH`: Row in `Values` does not match `len(Fields)`.
* **8**: `E_TYPE_MISMATCH`: Cell value does not match declared type.
* **9**: `E_POL002_PRIMITIVE_VIOLATION`: 104a contains complex types (`array`/`object`).
* **10**: `E_RESERVED_KEY_COLLISION`: Top-level key begins with reserved `_`.
* **11**: `E_104DB_MISSING_DISCRIMINATOR`: First field is not `Record_Type_Parent`.
* **12**: `E_104DB_UNASSIGNED_FIELD`: Field missing `Record_Type_Parent` ownership.

---

Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
