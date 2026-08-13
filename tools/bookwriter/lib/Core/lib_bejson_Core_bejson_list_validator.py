"""
Library:        lib_bejson_Core_bejson_list_validator.py
Family:         Core
Description:    Hierarchical list validator. Extends standard structural validator.
Version:        1.3.1
Date:            2026-07-09
Author:         Elton Boehnen
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  6c1e9a3f-8b5d-4e7c-9a2f-1d6b8e3c9f47
"""

from typing import Any, Dict
import lib_bejson_Core_bejson_validator as StandardValidator
import lib_bejson_Core_bejson_core as BEJSONCore

def validate_list(doc_data: dict) -> Dict[str, Any]:
    """
    doc_data: an already-loaded BEJSON document dict (e.g. from
    BEJSONCore.bejson_core_load_file() or MFDBCore.mfdb_core_get_entity_doc()).
    This function no longer performs any file I/O itself — the caller
    (typically MFDBCore) is responsible for loading the document.
    """
    # 1. Structural Validation (Sourced from Core) — validate_bejson() accepts
    # a dict natively (is_file=False, and bejson_validator_check_json_syntax
    # passes dicts straight through), so this no longer routes through the
    # file-path-only bejson_validator_validate_file().
    res = StandardValidator.validate_bejson(doc_data, is_file=False)
    if not res.valid:
        return {"is_valid": False, "errors": res.errors}

    doc = doc_data

    # 2. BEJSON Format Version Constraint
    # Accepts both "104a" (standalone list documents) and "104" (standard
    # MFDBCore entity docs, which carry Parent_Hierarchy instead of being
    # manifests themselves). Per Directive 2, Category/Nav are now regular
    # MFDBCore entities like Page/Post/Media, and MFDBCore.mfdb_core_get_entity_doc()
    # returns those as Format_Version "104" — the hierarchy check below only
    # cares about id/parent_id being present, not which of the two valid
    # BEJSON list-shaped formats the doc uses.
    if doc.get("Format_Version") not in ("104a", "104"):
        return {"is_valid": False, "errors": ["List Manager requires BEJSON 104 or 104a format."]}

    # 3. List Logic (Hierarchy & Integrity)
    values = doc.get("Values", [])
    # R7: use BEJSONCore field map cache instead of re-building per call
    f_map = BEJSONCore.bejson_core_get_field_map(doc)
    if "id" not in f_map or "parent_id" not in f_map:
        return {"is_valid": False, "errors": ["Missing core list fields: id, parent_id"]}
        
    id_idx = f_map["id"]
    pid_idx = f_map["parent_id"]
    
    ids = set()
    parent_refs = {}
    
    for i, row in enumerate(values):
        uid = row[id_idx]
        pid = row[pid_idx]
        if uid in ids:
            return {"is_valid": False, "errors": [f"Duplicate ID detected: {uid}"]}
        ids.add(uid)
        if pid: parent_refs[uid] = pid

    for uid, pid in parent_refs.items():
        if pid not in ids:
            return {"is_valid": False, "errors": [f"Orphan detected: {uid} -> {pid}"]}
        path = {uid}
        curr = pid
        while curr:
            if curr in path:
                return {"is_valid": False, "errors": [f"Circular dependency: {uid}"]}
            path.add(curr)
            curr = parent_refs.get(curr)

    return {"is_valid": True, "errors": [], "stats": {"item_count": len(ids)}}

if __name__ == "__main__":
    print("Python List Validator v1.3.0 Loaded (I/O decoupled, error branch fixed).")
