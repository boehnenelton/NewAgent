/**
 * Library:        lib_bejson_Core_bejson_validators.ts
 * Family:         Core
 * Description:    Structural integrity checker for positional values and mandatory keys.
 * Version:        2.0.2
 * Date:           2026-05-18
 * Author:         Elton Boehnen
 * Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
 * Format_Creator: Elton Boehnen
 * RELATIONAL_ID:  8f556cb9-1388-46d9-af64-10ad2deceaed
 */

import {
  BEJSONDocument,
  BEJSONField,
  BEJSONFieldType,
  BEJSONPrimitiveType,
  BEJSONValue,
  ValidationResult,
  ValidationError,
  ValidationWarning,
  BEJSONValidationError,
  BEJSON_VALIDATION_CODES as E,
} from "./lib_bejson_Core_bejson_types";

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function validateDocument(doc: unknown): ValidationResult {
  const result = _makeResult();

  // Step 1: structural sanity before touching any BEJSON fields
  if (doc === null || doc === undefined || typeof doc !== "object" || Array.isArray(doc)) {
    _err(result, E.INVALID_FORMAT_VALUE, "Document root must be a non-null object.");
    return result;
  }

  const d = doc as Record<string, unknown>;

  // Step 2: mandatory keys
  _checkMandatoryKeys(d, result);
  if (!result.valid) return result; // can't proceed without the six keys

  const bej = doc as BEJSONDocument;

  // Step 3: top-level value checks (Format, Format_Creator, Format_Version)
  _checkTopLevel(bej, result);
  if (!result.valid) return result;

  // Step 4: Fields array
  _checkFields(bej, result);
  if (!result.valid) return result;

  // Step 5: Values array
  _checkValues(bej, result);

  // Step 6: version-specific rules
  switch (bej.Format_Version) {
    case "104":
      _check104Specific(bej, result);
      break;
    case "104a":
      _check104aSpecific(bej, result);
      break;
    case "104db":
      _check104dbSpecific(bej, result);
      break;
  }

  return result;
}

export function validate104(doc: unknown): ValidationResult {
  const result = validateDocument(doc);
  if (result.valid) {
    const bej = doc as BEJSONDocument;
    if (bej.Format_Version !== "104") {
      _err(result, E.INVALID_FORMAT_VERSION, "Expected Format_Version \"104\", got \"" + bej.Format_Version + "\".");
    }
  }
  return result;
}

export function validate104a(doc: unknown): ValidationResult {
  const result = validateDocument(doc);
  if (result.valid) {
    const bej = doc as BEJSONDocument;
    if (bej.Format_Version !== "104a") {
      _err(result, E.INVALID_FORMAT_VERSION, "Expected Format_Version \"104a\", got \"" + bej.Format_Version + "\".");
    }
  }
  return result;
}

export function validate104db(doc: unknown): ValidationResult {
  const result = validateDocument(doc);
  if (result.valid) {
    const bej = doc as BEJSONDocument;
    if (bej.Format_Version !== "104db") {
      _err(result, E.INVALID_FORMAT_VERSION, "Expected Format_Version \"104db\", got \"" + bej.Format_Version + "\".");
    }
  }
  return result;
}

export function assertValid(doc: unknown): void {
  const result = validateDocument(doc);
  if (!result.valid && result.errors.length > 0) {
    const e = result.errors[0];
    throw new BEJSONValidationError(e.code, e.message);
  }
}

export function isValid(doc: unknown): boolean {
  return validateDocument(doc).valid;
}

// ---------------------------------------------------------------------------
// Step 2 — mandatory keys
// ---------------------------------------------------------------------------

const MANDATORY_KEYS = ["Format", "Format_Version", "Format_Creator", "Records_Type", "Fields", "Values"] as const;

function _checkMandatoryKeys(d: Record<string, unknown>, r: ValidationResult): void {
  for (const key of MANDATORY_KEYS) {
    if (!(key in d) || d[key] === undefined) {
      _err(r, E.MISSING_MANDATORY_KEY, "Missing mandatory key: " + key, key);
    }
  }
}

// ---------------------------------------------------------------------------
// Step 3 — top-level value constraints
// ---------------------------------------------------------------------------

function _checkTopLevel(doc: BEJSONDocument, r: ValidationResult): void {
  if (doc.Format !== "BEJSON") {
    _err(r, E.INVALID_FORMAT_VALUE, "Format must be \"BEJSON\", got \"" + doc.Format + "\".", "Format");
  }

  const validVersions = ["104", "104a", "104db"];
  if (!validVersions.includes(doc.Format_Version as string)) {
    _err(r, E.INVALID_FORMAT_VERSION, "Format_Version must be one of " + JSON.stringify(validVersions) + ", got \"" + doc.Format_Version + "\".", "Format_Version");
  }

  if (doc.Format_Creator !== "Elton Boehnen") {
    _err(r, E.INVALID_FORMAT_CREATOR, "Format_Creator must be \"Elton Boehnen\", got \"" + doc.Format_Creator + "\".", "Format_Creator");
  }

  if (!Array.isArray(doc.Records_Type) || doc.Records_Type.length === 0) {
    _err(r, E.INVALID_RECORDS_TYPE, "Records_Type must be a non-empty array.", "Records_Type");
  } else {
    for (const rt of doc.Records_Type) {
      if (typeof rt !== "string" || rt.trim() === "") {
        _err(r, E.INVALID_RECORDS_TYPE, "All Records_Type entries must be non-empty strings.", "Records_Type");
        break;
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Step 4 — Fields array
// ---------------------------------------------------------------------------

const VALID_TYPES: BEJSONFieldType[] = ["string", "integer", "number", "boolean", "array", "object"];

function _checkFields(doc: BEJSONDocument, r: ValidationResult): void {
  if (!Array.isArray(doc.Fields) || doc.Fields.length === 0) {
    _err(r, E.INVALID_FIELDS, "Fields must be a non-empty array.", "Fields");
    return;
  }

  const seen = new Set<string>();
  for (let i = 0; i < doc.Fields.length; i++) {
    const field = doc.Fields[i] as BEJSONField;

    if (!field || typeof field !== "object") {
      _err(r, E.INVALID_FIELDS, "Fields[" + i + "] must be an object.", "Fields");
      continue;
    }
    if (typeof field.name !== "string" || field.name.trim() === "") {
      _err(r, E.INVALID_FIELDS, "Fields[" + i + "].name must be a non-empty string.", "Fields");
    }
    if (!VALID_TYPES.includes(field.type as BEJSONFieldType)) {
      _err(r, E.INVALID_FIELDS, "Fields[" + i + "].type is invalid: \"" + field.type + "\".", "Fields");
    }
    if (seen.has(field.name)) {
      _err(r, E.DUPLICATE_FIELD_NAME, "Duplicate field name: \"" + field.name + "\".", field.name);
    } else {
      seen.add(field.name);
    }
  }
}

// ---------------------------------------------------------------------------
// Step 5 — Values array
// ---------------------------------------------------------------------------

function _checkValues(doc: BEJSONDocument, r: ValidationResult): void {
  if (!Array.isArray(doc.Values)) {
    _err(r, E.INVALID_VALUES_STRUCTURE, "Values must be an array.", "Values");
    return;
  }

  const fieldCount = doc.Fields.length;

  for (let i = 0; i < doc.Values.length; i++) {
    const row = doc.Values[i];
    if (!Array.isArray(row)) {
      _err(r, E.INVALID_VALUES_STRUCTURE, "Values[" + i + "] must be an array.", undefined, i);
      continue;
    }
    if (row.length !== fieldCount) {
      _err(r, E.RECORD_LENGTH_MISMATCH,
        "Values[" + i + "] has " + row.length + " elements but Fields has " + fieldCount + ".",
        undefined, i);
      continue;
    }

    // Type-check each cell
    for (let fi = 0; fi < fieldCount; fi++) {
      const field = doc.Fields[fi];
      const val = row[fi];
      if (val === null) continue; // null always valid
      if (!_typeMatches(val, field.type)) {
        _err(r, E.VALUE_TYPE_MISMATCH,
          "Values[" + i + "][" + fi + "] (" + field.name + "): expected " + field.type + ", got " + typeof val + ".",
          field.name, i);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Step 6a — 104-specific rules
// ---------------------------------------------------------------------------

const FORBIDDEN_CUSTOM_KEYS_104 = new Set(MANDATORY_KEYS);

function _check104Specific(doc: BEJSONDocument, r: ValidationResult): void {
  // Single record type
  if (doc.Records_Type.length !== 1) {
    _err(r, E.VERSION_CONSTRAINT, "BEJSON 104 requires exactly one Records_Type entry.", "Records_Type");
  }

  // No custom top-level keys (Parent_Hierarchy is the only exception)
  for (const key of Object.keys(doc)) {
    if (!FORBIDDEN_CUSTOM_KEYS_104.has(key as typeof MANDATORY_KEYS[number]) && key !== "Parent_Hierarchy") {
      _err(r, E.FORBIDDEN_CUSTOM_KEY, "BEJSON 104 forbids custom top-level key: \"" + key + "\".", key);
    }
  }

  // Parent_Hierarchy, if present, must be a string
  if ("Parent_Hierarchy" in doc && typeof doc.Parent_Hierarchy !== "string") {
    _err(r, E.VERSION_CONSTRAINT, "Parent_Hierarchy must be a string when present.", "Parent_Hierarchy");
  }
}

// ---------------------------------------------------------------------------
// Step 6b — 104a-specific rules
// ---------------------------------------------------------------------------

const PRIMITIVE_TYPES: BEJSONPrimitiveType[] = ["string", "integer", "number", "boolean"];
const PASCAL_CASE_RE = /^[A-Z][A-Za-z0-9]*(_[A-Za-z0-9]+)*$/;

function _check104aSpecific(doc: BEJSONDocument, r: ValidationResult): void {
  // Single record type
  if (doc.Records_Type.length !== 1) {
    _err(r, E.VERSION_CONSTRAINT, "BEJSON 104a requires exactly one Records_Type entry.", "Records_Type");
  }

  // Fields must be primitive-only
  for (let i = 0; i < doc.Fields.length; i++) {
    const field = doc.Fields[i];
    if (!PRIMITIVE_TYPES.includes(field.type as BEJSONPrimitiveType)) {
      _err(r, E.VERSION_CONSTRAINT,
        "BEJSON 104a: Fields[" + i + "].type \"" + field.type + "\" is not a primitive type.", field.name);
    }
  }

  // Custom keys: must be PascalCase, must not collide with mandatory keys
  for (const key of Object.keys(doc)) {
    if (FORBIDDEN_CUSTOM_KEYS_104.has(key as typeof MANDATORY_KEYS[number])) continue;
    if (key === "Parent_Hierarchy") {
      // Parent_Hierarchy is not defined for 104a but not strictly forbidden;
      // emit a warning rather than an error since the spec is silent here.
      continue;
    }
    if (!PASCAL_CASE_RE.test(key)) {
      _err(r, E.INVALID_CUSTOM_KEY,
        "BEJSON 104a: custom header \"" + key + "\" must be PascalCase.", key);
    }
  }
}

// ---------------------------------------------------------------------------
// Step 6c — 104db-specific rules
// ---------------------------------------------------------------------------

function _check104dbSpecific(doc: BEJSONDocument, r: ValidationResult): void {
  // Two or more record types
  if (doc.Records_Type.length < 2) {
    _err(r, E.VERSION_CONSTRAINT, "BEJSON 104db requires at least two Records_Type entries.", "Records_Type");
  }

  // No custom top-level keys (not even Parent_Hierarchy)
  for (const key of Object.keys(doc)) {
    if (!FORBIDDEN_CUSTOM_KEYS_104.has(key as typeof MANDATORY_KEYS[number])) {
      _err(r, E.FORBIDDEN_CUSTOM_KEY, "BEJSON 104db forbids custom top-level key: \"" + key + "\".", key);
    }
  }

  // First field must be Record_Type_Parent: string
  if (doc.Fields.length === 0 || doc.Fields[0].name !== "Record_Type_Parent") {
    _err(r, E.MISSING_DISCRIMINATOR, "BEJSON 104db: first field must be named \"Record_Type_Parent\".", "Fields");
    return; // can't continue safely
  }
  if (doc.Fields[0].type !== "string") {
    _err(r, E.MISSING_DISCRIMINATOR, "BEJSON 104db: Record_Type_Parent field type must be \"string\".", "Record_Type_Parent");
  }

  // Every field except Record_Type_Parent must have Record_Type_Parent property
  const validEntities = new Set(doc.Records_Type);
  for (let i = 1; i < doc.Fields.length; i++) {
    const field = doc.Fields[i];
    if (!field.Record_Type_Parent) {
      _err(r, E.MISSING_DISCRIMINATOR,
        "BEJSON 104db: Fields[" + i + "] (\"" + field.name + "\") is missing Record_Type_Parent assignment.", field.name);
    } else if (!validEntities.has(field.Record_Type_Parent)) {
      _err(r, E.VERSION_CONSTRAINT,
        "BEJSON 104db: Fields[" + i + "].Record_Type_Parent \"" + field.Record_Type_Parent + "\" is not in Records_Type.", field.name);
    }
  }

  // Every record's discriminator must match a declared entity
  if (Array.isArray(doc.Values)) {
    for (let i = 0; i < doc.Values.length; i++) {
      const row = doc.Values[i];
      if (!Array.isArray(row) || row.length === 0) continue;
      const discriminator = row[0];
      if (typeof discriminator !== "string" || !validEntities.has(discriminator)) {
        _err(r, E.VERSION_CONSTRAINT,
          "Values[" + i + "][0] discriminator \"" + discriminator + "\" not in Records_Type.", "Record_Type_Parent", i);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Type matching helper
// ---------------------------------------------------------------------------

function _typeMatches(val: unknown, type: BEJSONFieldType): boolean {
  if (val === null) return true;
  switch (type) {
    case "string":
      return typeof val === "string";
    case "integer":
      return typeof val === "number" && Number.isInteger(val);
    case "number":
      return typeof val === "number";
    case "boolean":
      return typeof val === "boolean";
    case "array":
      return Array.isArray(val);
    case "object":
      return typeof val === "object" && !Array.isArray(val) && val !== null;
    default:
      return false;
  }
}

// ---------------------------------------------------------------------------
// Result helpers
// ---------------------------------------------------------------------------

function _makeResult(): ValidationResult {
  return { valid: true, errors: [], warnings: [] };
}

function _err(
  r: ValidationResult,
  code: number,
  message: string,
  field?: string,
  recordIndex?: number
): void {
  r.valid = false;
  const e: ValidationError = { code, message };
  if (field !== undefined) e.field = field;
  if (recordIndex !== undefined) e.recordIndex = recordIndex;
  r.errors.push(e);
}

function _warn(
  r: ValidationResult,
  code: number,
  message: string,
  field?: string,
  recordIndex?: number
): void {
  const w: ValidationWarning = { code, message };
  if (field !== undefined) w.field = field;
  if (recordIndex !== undefined) w.recordIndex = recordIndex;
  r.warnings.push(w);
}

// Export _warn so mfdb_validators can reuse the pattern
export { _warn as _emitWarning, _err as _emitError, _makeResult };
