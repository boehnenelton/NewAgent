# Chapter 1: Architecture, Core Schemas, and TypeScript Type System

## Introduction & High-Level Architecture

The BEJSON (BOEHNEN ELTON JSON) specification addresses a fundamental inefficiency in traditional JSON-based data exchange: structural duplication. In standard JSON array-of-objects representations, key names are repeated across every item, inflating payload size and increasing serialization/deserialization overhead. BEJSON replaces this verbose structure with a high-density, matrix-oriented JSON architecture. By decoupling document metadata and field definitions from data rows, BEJSON separates the schema declaration from the raw value payload while retaining complete readability and native compatibility with JSON parsers.

At its structural core, a BEJSON document splits a dataset into three explicit sections:
1. **Header Metadata**: Top-level keys (`Format`, `Format_Version`, `Format_Creator`, `Records_Type`) establishing the schema type, creator attribution, and protocol versioning.
2. **Field Schema Matrix (`Fields`)**: An array of `BEJSONField` object descriptors that define field names and primitive data types in strict ordinal order.
3. **Value Matrix (`Values`)**: A two-dimensional array (`BEJSONValue[][]`) where each outer element represents a record, and each inner element contains primitive data values aligned strictly to the ordinal positions in `Fields`.

```
Traditional JSON (Verbose):
[
  { "id": 101, "name": "Engine", "active": true },
  { "id": 102, "name": "Grid",   "active": false }
]

BEJSON Format (High-Density Tabular):
{
  "Format": "BEJSON",
  "Format_Version": "104",
  "Format_Creator": "Elton Boehnen",
  "Records_Type": ["Component"],
  "Fields": [
    { "name": "id",     "type": "integer" },
    { "name": "name",   "type": "string" },
    { "name": "active", "type": "boolean" }
  ],
  "Values": [
    [101, "Engine", true],
    [102, "Grid",   false]
  ]
}
```

This structural separation provides significant benefits:
- **Payload Compression**: Transmitting key names once at the top of the document significantly cuts payload footprint for large datasets before secondary byte compression (such as gzip or zstd).
- **Constant-Time Field Map Lookups**: Systems can pre-calculate field offsets, converting record deserialization into low-overhead array index lookups rather than key-string matching.
- **Relational Integrity**: MFDB (Multi File Database) architecture uses BEJSON schemas across separate physical files, establishing multi-file relational boundaries with explicit parent-child hierarchies.

### Module Taxonomy and System Architecture

The TypeScript implementation of Core BEJSON is organized into modular subsystems under the `Core/` tree, with secondary extensions (such as `Gaming/`) re-exported at the library boundary.

```
                    ┌─────────────────────────────────────────┐
                    │              Core/index.ts              │
                    │      (Public API & Re-exports)          │
                    └──────────────────┬──────────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
┌───────▼──────────────┐    ┌──────────▼───────────┐    ┌─────────────▼────────────┐
│ bejson_types.ts      │    │ bejson_core.ts       │    │ bejson_validators.ts     │
│ - Type Definitions   │    │ - Low-level Parsing  │    │ - 104 / 104a / 104db     │
│ - Interfaces         │    │ - Serialization      │    │   Validation Engines     │
│ - BEJSONCoreError    │    │ - CRUD Mutators      │    │ - Document Assertions    │
└──────────────────────┘    └──────────────────────┘    └──────────────────────────┘
        │                              │                              │
        ├──────────────────────────────┼──────────────────────────────┘
        │                              │
┌───────▼──────────────┐    ┌──────────▼───────────┐
│ bejson_chunking.ts   │    │ mfdb_validators.ts   │
│ - Workspace Chunker  │    │ - Manifest Checker   │
│ - Unchunk Engine     │    │ - Entity Integrity   │
│ - MFDB 1.32 Package  │    │ - MFDB Database Rules│
└──────────────────────┘    └──────────────────────┘
```

- `lib_bejson_Core_bejson_types.ts`: Contains the foundational TypeScript type definitions, primitive constraints, enum error codes, and exception classes.
- `lib_bejson_Core_bejson_core.ts`: Contains low-level document parsing, canonical JSON serialization, array index management, record object extraction, and mutating operations (`appendRecord`, `updateRecord`, `deleteRecord`).
- `lib_bejson_Core_bejson_validators.ts`: Contains strict schema validation routines enforcing rule sets for BEJSON 104, 104a, and 104db formats.
- `lib_bejson_Core_bejson_field_map.ts`: Provides mapping utilities that project flat array rows into typed domain objects or dynamic record dictionaries.
- `lib_bejson_Core_bejson_chunking.ts`: Handles project directory serialization into standardized single-file archives (`Chunked-104a`), base64 binary preservation, and `MFDB132Archive` session lifecycle management.
- `lib_bejson_Core_mfdb_core.ts` & `lib_bejson_Core_mfdb_validators.ts`: Contain relational container logic for Multi File Databases (MFDB), manifest tracking, cross-entity validation, and multi-file transaction safety.

---

## The BEJSON Schema Standard (104, 104a, and 104db)

The core specification divides document layouts into three format variants optimized for distinct system workloads: **104**, **104a**, and **104db**.

### 1. BEJSON 104: Standard Tabular Entity Format

BEJSON 104 is the baseline schema for uniform single-entity collections. It requires explicit metadata headers, a typed field definitions array, and a two-dimensional values matrix.

#### Structural Specification
- **Format Requirements**: `Format` must equal `"BEJSON"`. `Format_Version` must equal `"104"`. `Format_Creator` must equal `"Elton Boehnen"`.
- **Records_Type**: A tuple containing exactly one string element declaring the entity type (e.g., `["User"]`).
- **Fields Specification**: An array of `BEJSONField` objects. Allowed field types include primitive types (`"string"`, `"integer"`, `"number"`, `"boolean"`, `"null"`, `"array"`, `"object"`) as well as extended types (`"datetime"`, `"date"`, `"time"`, `"email"`, `"uuid"`, `"url"`, `"enum"`).
- **Optional Header**: `Parent_Hierarchy` (string), declaring relational pathing within nested namespace systems.

```json
{
  "Format": "BEJSON",
  "Format_Version": "104",
  "Format_Creator": "Elton Boehnen",
  "Records_Type": ["InventoryItem"],
  "Fields": [
    { "name": "sku", "type": "string" },
    { "name": "quantity", "type": "integer" },
    { "name": "unit_cost", "type": "number" },
    { "name": "in_stock", "type": "boolean" }
  ],
  "Values": [
    ["SKU-001", 150, 12.99, true],
    ["SKU-002", 0, 45.50, false]
  ]
}
```

### 2. BEJSON 104a: Metadata and Project Chunking Format

BEJSON 104a is a streamlined, flat specification designed for configuration files, document metadata, and filesystem archives (`Chunked-104a`).

#### Structural Specification
- **Format Requirements**: `Format` must equal `"BEJSON"`. `Format_Version` must equal `"104a"`.
- **Records_Type**: A tuple containing exactly one string element (e.g., `["Chunked"]` or `["MFDB-132"]`).
- **Fields Constraint**: Field type definitions in 104a are strictly limited to basic scalar primitives: `"string"`, `"integer"`, `"number"`, and `"boolean"`. Nested types (`"array"`, `"object"`) are invalid in 104a field descriptors.
- **Custom PascalCase Headers**: 104a allows top-level custom metadata headers (e.g., `Schema_Name`, `Package_Version`, `Session_Is_Mounted`). Every non-standard header key must follow strict PascalCase naming rules matching the regular expression `/^[A-Z][a-zA-Z0-9]*(_[A-Z0-9][a-zA-Z0-9]*)*$/`.

```json
{
  "Format": "BEJSON",
  "Format_Version": "104a",
  "Format_Creator": "Elton Boehnen",
  "Schema_Name": "Chunked-104a",
  "Schema_Version": "1.0.1",
  "Chunk_Date": "2026-08-08",
  "Session_Is_Mounted": false,
  "Mount_Path": "",
  "Package_Version": "1",
  "Records_Type": ["Chunked"],
  "Fields": [
    { "name": "File_Name", "type": "string" },
    { "name": "File_Extension", "type": "string" },
    { "name": "File_Content", "type": "string" },
    { "name": "File_Version", "type": "string" },
    { "name": "File_Hash", "type": "string" },
    { "name": "Relative_Path", "type": "string" },
    { "name": "Is_Binary", "type": "boolean" },
    { "name": "Is_Mounted", "type": "boolean" }
  ],
  "Values": [
    ["index.ts", ".ts", "console.log('init');", "1.0.0", "e3b0c442...", "src/index.ts", false, false]
  ]
}
```

### 3. BEJSON 104db: Multi-Entity Relational Format

BEJSON 104db consolidates multiple distinct record types into a single physical document, serving as an inline relational database container.

#### Structural Specification
- **Format Requirements**: `Format` must equal `"BEJSON"`. `Format_Version` must equal `"104db"`.
- **Records_Type**: An array containing **two or more** string entity identifiers (e.g., `["Customer", "Order", "LineItem"]`).
- **Discriminator Key**: The first field in the `Fields` array **must** be named `Record_Type_Parent` with type `"string"`.
- **Values Layout**: Every row array in `Values` must set its index `0` element to one of the string identifiers declared in `Records_Type`. This discriminator tags the entity schema for that row, while trailing fields corresponding to inactive entity attributes are populated with `null`.

```json
{
  "Format": "BEJSON",
  "Format_Version": "104db",
  "Format_Creator": "Elton Boehnen",
  "Records_Type": ["Customer", "Order"],
  "Fields": [
    { "name": "Record_Type_Parent", "type": "string" },
    { "name": "Entity_Id", "type": "string" },
    { "name": "Customer_Name", "type": "string" },
    { "name": "Order_Total", "type": "number" }
  ],
  "Values": [
    ["Customer", "CUST-100", "Acme Corp", null],
    ["Order", "ORD-5001", null, 1250.75]
  ]
}
```

### Comparative Schema Specification Matrix

| Feature / Header | BEJSON 104 | BEJSON 104a | BEJSON 104db |
| :--- | :--- | :--- | :--- |
| `Format` | `"BEJSON"` | `"BEJSON"` | `"BEJSON"` |
| `Format_Version` | `"104"` | `"104a"` | `"104db"` |
| `Format_Creator` | `"Elton Boehnen"` | `"Elton Boehnen"` | `"Elton Boehnen"` |
| `Records_Type` Length | Exactly 1 string | Exactly 1 string | 2 or more strings |
| Field Type Support | Primitives & Extended Types | Basic Primitives Only | Primitives & Extended Types |
| Discriminator Field | Not required | Not required | Mandatory at `Fields[0]` (`Record_Type_Parent`) |
| Custom Top-Level Headers | Disallowed | Allowed (PascalCase enforce) | Disallowed |
| `Parent_Hierarchy` | Optional | Disallowed | Disallowed |

---

## The TypeScript Type System for BEJSON

The Core BEJSON type system provides strict type contracts that balance dynamic JSON flexibility with static type safety. The types are defined in `lib_bejson_Core_bejson_types.ts`.

### Core Data Primitive Types

BEJSON constrains supported field data types using literal union types:

```typescript
export type BEJSONPrimitiveTypeName =
  | "string"
  | "integer"
  | "number"
  | "boolean"
  | "null"
  | "array"
  | "object";

export type BEJSONExtendedTypeName =
  | "datetime"
  | "date"
  | "time"
  | "email"
  | "uuid"
  | "url"
  | "enum";

export type BEJSONFieldTypeName = BEJSONPrimitiveTypeName | BEJSONExtendedTypeName;

export type BEJSONValue =
  | string
  | number
  | boolean
  | null
  | BEJSONValue[]
  | { [key: string]: BEJSONValue };
```

### Field Definitions and Document Interfaces

The `BEJSONField` interface specifies field schema definitions, including validation metadata for structural checkers:

```typescript
export interface BEJSONField {
  name: string;
  type: BEJSONFieldTypeName;
  description?: string;
  required?: boolean;
  enum_values?: string[];
  pattern?: string;
  minimum?: number;
  maximum?: number;
}

export interface BEJSONDocument {
  Format: "BEJSON";
  Format_Version: "104" | "104a" | "104db" | string;
  Format_Creator: "Elton Boehnen" | string;
  Records_Type: string[];
  Fields: BEJSONField[];
  Values: BEJSONValue[][];
  Parent_Hierarchy?: string;
  [key: string]: unknown;
}
```

### Specialized Chunking Types

Project packaging and workspace mounting rely on `ChunkedDocument` and its associated interfaces, imported from `lib_bejson_Core_bejson_chunking.ts`:

```typescript
export interface BejsonField {
  name: string;
  type: string;
}

export interface ChunkedDocument {
  Format: string;
  Format_Version: string;
  Format_Creator: string;
  Schema_Name: string;
  Schema_Version: string;
  Schema_Description: string;
  Chunk_Date: string;
  Session_Is_Mounted: boolean;
  Mount_Path: string;
  Records_Type: string[];
  Fields: BejsonField[];
  Values: any[][];
  Package_Version?: string;
  MFDB_Version?: string;
  DB_Name?: string;
  Package_Format?: string;
  [key: string]: any;
}
```

### Exception Hierarchy and Error Class Design

Errors in Core BEJSON inherit from `BEJSONCoreError`, which attaches a system error code from `BEJSON_CORE_CODES` to native JavaScript `Error` instances.

```typescript
export enum BEJSON_CORE_CODES {
  PARSE_ERROR = "BEJSON_PARSE_ERROR",
  SERIALIZATION_ERROR = "BEJSON_SERIALIZATION_ERROR",
  VALIDATION_ERROR = "BEJSON_VALIDATION_ERROR",
  FIELD_NOT_FOUND = "BEJSON_FIELD_NOT_FOUND",
  INVALID_INDEX = "BEJSON_INVALID_INDEX",
  INVALID_ROW_LENGTH = "BEJSON_INVALID_ROW_LENGTH",
  NULL_DOCUMENT = "BEJSON_NULL_DOCUMENT",
  TYPE_MISMATCH = "BEJSON_TYPE_MISMATCH",
  UNSUPPORTED_OPERATION = "BEJSON_UNSUPPORTED_OPERATION",
}

export class BEJSONCoreError extends Error {
  public readonly code: BEJSON_CORE_CODES;

  constructor(code: BEJSON_CORE_CODES, message: string) {
    super(`[${code}] ${message}`);
    this.name = "BEJSONCoreError";
    this.code = code;
    Object.setPrototypeOf(this, BEJSONCoreError.prototype);
  }
}
```

Using custom exception classes enables precise runtime handling across parsing and validation routines:

```typescript
import { parse, BEJSONCoreError, BEJSON_CORE_CODES } from "./Core";

try {
  const doc = parse(rawInputString);
} catch (err) {
  if (err instanceof BEJSONCoreError) {
    switch (err.code) {
      case BEJSON_CORE_CODES.PARSE_ERROR:
        console.error("Syntax error in raw JSON payload:", err.message);
        break;
      case BEJSON_CORE_CODES.NULL_DOCUMENT:
        console.error("Received empty or undefined document body.");
        break;
      default:
        console.error("Core BEJSON failure:", err.message);
    }
  }
}
```

---

## Core Factories and Document Lifecycle Initialization

Constructing compliant BEJSON documents manually can lead to schema errors, such as missing required header keys or mismatched field indexes. Core BEJSON provides three baseline factory functions in `lib_bejson_Core_bejson_core.ts` to automate document creation: `createEmpty104`, `createEmpty104a`, and `createEmpty104db`.

### 1. Initializing Standard Documents (`createEmpty104`)

The `createEmpty104` factory constructs an empty 104 format document structure, accepting field definitions, optional initial row matrices, and an optional parent hierarchy string.

```typescript
export function createEmpty104(
  recordType: string,
  fields: BEJSONField[],
  values: BEJSONValue[][] = [],
  parentHierarchy?: string
): BEJSONDocument {
  const doc: BEJSONDocument = {
    Format: "BEJSON",
    Format_Version: "104",
    Format_Creator: "Elton Boehnen",
    Records_Type: [recordType],
    Fields: fields,
    Values: values,
  };
  if (parentHierarchy !== undefined) {
    (doc as Record<string, unknown>)["Parent_Hierarchy"] = parentHierarchy;
  }
  return doc;
}
```

#### Application Example
```typescript
import { createEmpty104, BEJSONField } from "./Core";

const userFields: BEJSONField[] = [
  { name: "user_id", type: "uuid", required: true },
  { name: "username", type: "string", required: true },
  { name: "login_count", type: "integer" },
  { name: "is_active", type: "boolean" }
];

const userDoc = createEmpty104("UserAccount", userFields, [], "System/Auth");
```

### 2. Initializing Configuration and Metadata Documents (`createEmpty104a`)

The `createEmpty104a` factory initializes a 104a format metadata document. Custom header values passed to the factory are spread directly into the top-level output document.

```typescript
export function createEmpty104a(
  recordType: string,
  fields: BEJSONField[],
  customHeaders: Record<string, string | number | boolean> = {}
): BEJSONDocument {
  return {
    Format: "BEJSON",
    Format_Version: "104a",
    Format_Creator: "Elton Boehnen",
    Records_Type: [recordType],
    Fields: fields,
    Values: [],
    ...customHeaders,
  };
}
```

#### Application Example
```typescript
import { createEmpty104a, BEJSONField } from "./Core";

const configFields: BEJSONField[] = [
  { name: "Setting_Key", type: "string" },
  { name: "Setting_Value", type: "string" },
  { name: "Is_Overridden", type: "boolean" }
];

const appConfig = createEmpty104a("AppConfig", configFields, {
  Environment: "Production",
  Deployment_Region: "us-east-1",
  Max_Connections: 500
});
```

### 3. Initializing Multi-Entity Databases (`createEmpty104db`)

The `createEmpty104db` factory configures multi-entity container documents. It validates that the schema includes at least two entity types and sets up the required `Record_Type_Parent` discriminator field at position `0`.

```typescript
export function createEmpty104db(
  recordTypes: [string, string, ...string[]],
  fields: BEJSONField[]
): BEJSONDocument {
  return {
    Format: "BEJSON",
    Format_Version: "104db",
    Format_Creator: "Elton Boehnen",
    Records_Type: recordTypes,
    Fields: fields,
    Values: [],
  };
}
```

#### Application Example
```typescript
import { createEmpty104db, BEJSONField } from "./Core";

const relationalFields: BEJSONField[] = [
  { name: "Record_Type_Parent", type: "string" },
  { name: "Primary_Key", type: "string" },
  { name: "Payload_Data", type: "string" }
];

const dbDoc = createEmpty104db(
  ["HeaderEntity", "DetailEntity"],
  relationalFields
);
```

---

## Structural Invariants and Serialized Byte Consistency

To maintain structural integrity across different language runtimes (TypeScript, JavaScript, Python, and Shell), Core BEJSON enforces four strict document invariants:

```
+-----------------------------------------------------------------------+
|                         BEJSON DOCUMENT MATRIX                        |
+-----------------------------------------------------------------------+
| Fields: [  F_0  ] [  F_1  ] [  F_2  ] ... [  F_(N-1)  ]               |
|            |         |         |                |                     |
|            v         v         v                v                     |
| Row 0:  [  v_00 ] [  v_01 ] [  v_02 ] ... [  v_0(N-1) ] -> Length N   |
| Row 1:  [  v_10 ] [  v_11 ] [  v_12 ] ... [  v_1(N-1) ] -> Length N   |
| Row R:  [  v_R0 ] [  v_R1 ] [  v_R2 ] ... [  v_R(N-1) ] -> Length N   |
+-----------------------------------------------------------------------+
|  INVARIANT 1: Row Length == Fields.length for EVERY Row               |
|  INVARIANT 2: Ordinal Index Alignment (Values[R][i] matches Fields[i])|
+-----------------------------------------------------------------------+
```

### 1. The Row Width Invariant

For every row $R$ in `Values`, the element count of $R$ must exactly match the element count of `Fields`:

$$\forall row \in \text{Values}, \quad row.\text{length} == \text{Fields}.\text{length}$$

Appending or updating a row with fewer or more elements than `Fields.length` throws a `BEJSON_INVALID_ROW_LENGTH` exception. Sparse datasets must explicitly pad omitted fields with `null` values.

### 2. Ordinal Index Alignment

The value at `Values[R][i]` corresponds strictly to the field descriptor at `Fields[i]`. Field values are matched by position rather than key name, eliminating key lookup overhead during processing.

### 3. Key Normalization and Underscore Stripping

During document serialization via `serialize(doc, indent)`, internal metadata attributes prefixed with an underscore (`_`) are stripped from the output. This allows runtime engines to attach temporary cache properties (e.g., `_keyCache` or index maps) to document objects in memory without polluting serialized output files.

```typescript
// Core implementation from lib_bejson_Core_bejson_core.ts
export function serialize(doc: BEJSONDocument, indent: number = 2): string {
  if (doc === null || doc === undefined) {
    throw new BEJSONCoreError(
      BEJSON_CORE_CODES.NULL_DOCUMENT,
      "Cannot serialize null or undefined document."
    );
  }
  try {
    const cleanDoc: Record<string, any> = {};
    for (const key in doc) {
      if (
        Object.prototype.hasOwnProperty.call(doc, key) &&
        !key.startsWith("_")
      ) {
        cleanDoc[key] = doc[key];
      }
    }
    return JSON.stringify(cleanDoc, null, indent || undefined);
  } catch (e) {
    throw new BEJSONCoreError(
      BEJSON_CORE_CODES.SERIALIZATION_ERROR,
      "Serialization failed: " + String(e)
    );
  }
}
```

### 4. Deterministic Cross-Language Serialization

When writing BEJSON documents to disk, engines use canonical formatting rules to ensure multi-platform consistency:
- Structural indentation defaults to exactly 2 spaces.
- Floating-point integers are normalized to exclude unnecessary trailing decimals (e.g., `12.0` serializes as `12`).
- String fields containing binary payload data (such as preserved file contents in `Chunked-104a` archives) must use standard Base64 encoding.
- Date and time field strings use ISO-8601 UTC format, ending with an explicit `"Z"` suffix (e.g., `"2026-08-08T12:00:00Z"`).

By enforcing these structural rules, Core BEJSON provides a consistent data interchange model that bridges static type safety in TypeScript with high-performance, deterministic cross-language serialization.