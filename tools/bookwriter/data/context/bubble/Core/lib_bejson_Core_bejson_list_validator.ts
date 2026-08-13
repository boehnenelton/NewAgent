/**
 * Library:        lib_bejson_Core_bejson_list_validator.ts
 * Family:         Core
 * Description:    TS implementation of the Hierarchical List Validator.
 * Version:        1.2.0
 * Date:           2026-08-08
 * Author:         Elton Boehnen
 * Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
 * Format_Creator: Elton Boehnen
 * RELATIONAL_ID:  bffb2451-b1b2-4147-882b-cc918a94a40f
 *
 * CHANGE (2026-08-08): LIB-C4 -- validateList() parsed jsonString twice
 * (once to validate, once into `doc`). Wasteful, not incorrect (same
 * string, deterministic parse) -- but a malformed jsonString threw a raw
 * JSON.parse SyntaxError instead of a clean ValidationResult. Parses
 * once now, wrapped in try/catch returning E.INVALID_JSON on failure.
 */

import { validateDocument } from "./lib_bejson_Core_bejson_validators";
import { BEJSONDocument, ValidationResult, BEJSON_VALIDATION_CODES as E } from "./lib_bejson_Core_bejson_types";

/**
 * Validates a Hierarchical List (BEJSON 104a with id and parent_id fields).
 * Ensures no orphans exist and structure follows positional integrity.
 */
export function validateList(jsonString: string): ValidationResult {
  // LIB-C4 fix (2026-08-08): was parsing jsonString twice (once to
  // validate, once into `doc`). Wasteful, not incorrect (same string,
  // deterministic parse) -- but a malformed jsonString would also throw
  // JSON.parse's raw SyntaxError instead of a clean ValidationResult.
  // Parse once and wrap in try/catch for a proper validation error.
  let doc: BEJSONDocument;
  try {
    doc = JSON.parse(jsonString);
  } catch (e) {
    return {
      valid: false,
      errors: [{ code: E.INVALID_JSON, message: `Malformed JSON: ${(e as Error).message}` }],
      warnings: []
    };
  }

  const result = validateDocument(doc);
  if (!result.valid) return result;

  if (doc.Format_Version !== "104a") {
    result.valid = false;
    result.errors.push({
      code: E.VERSION_CONSTRAINT,
      message: "Hierarchical List must be BEJSON 104a."
    });
    return result;
  }

  const idIdx = doc.Fields.findIndex(f => f.name === "id");
  const pidIdx = doc.Fields.findIndex(f => f.name === "parent_id");

  if (idIdx === -1 || pidIdx === -1) {
    result.valid = false;
    result.errors.push({
      code: E.MISSING_MANDATORY_KEY,
      message: "Hierarchical List requires 'id' and 'parent_id' fields."
    });
    return result;
  }

  const ids = new Set<any>();
  const parentRefs = new Map<any, any>();

  for (let i = 0; i < doc.Values.length; i++) {
    const row = doc.Values[i];
    const id = row[idIdx];
    const pid = row[pidIdx];

    if (id === null || id === undefined) {
      result.valid = false;
      result.errors.push({
        code: E.VALUE_TYPE_MISMATCH,
        message: `Row ${i} has null or undefined id.`,
        recordIndex: i
      });
      continue;
    }

    if (ids.has(id)) {
      result.valid = false;
      result.errors.push({
        code: E.DUPLICATE_FIELD_NAME, // Using duplicate field name code for duplicate IDs
        message: `Duplicate ID detected: ${id}`,
        recordIndex: i
      });
    }
    ids.add(id);

    if (pid !== null && pid !== undefined && pid !== "") {
      parentRefs.set(id, pid);
    }
  }

  // Orphan Detection
  for (const [uid, pid] of parentRefs.entries()) {
    if (!ids.has(pid)) {
      result.valid = false;
      result.errors.push({
        code: E.MFDB_FK_UNRESOLVED,
        message: `Orphan detected: Record ${uid} references non-existent parent ${pid}.`
      });
    }
  }

  // Cycle Detection (Bonus for TS implementation)
  for (const startId of parentRefs.keys()) {
    let currentId = startId;
    const visited = new Set([currentId]);
    while (parentRefs.has(currentId)) {
      currentId = parentRefs.get(currentId);
      if (visited.has(currentId)) {
        result.valid = false;
        result.errors.push({
          code: E.VERSION_CONSTRAINT,
          message: `Cycle detected in hierarchy involving ID: ${currentId}`
        });
        break;
      }
      visited.add(currentId);
    }
  }

  return result;
}
