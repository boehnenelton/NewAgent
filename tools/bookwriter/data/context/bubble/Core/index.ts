/**
 * Library:        index.ts
 * Family:         Core
 * Description:    Main entry point for TypeScript Core library family. Corrected paths (v2.0.3): removed self-referential ./Core/ prefix.
 * Version:        2.0.3
 * Date:           2026-06-28
 * Author:         Elton Boehnen
 * Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
 * Format_Creator: Elton Boehnen
 * RELATIONAL_ID:  21215340-3605-4581-b05c-f2970f9b1892
 */

// Types & error classes
export * from "./lib_bejson_Core_bejson_types";

// Core operations (parse, serialize, record CRUD)
export * from "./lib_bejson_Core_bejson_core";
export * from "./lib_bejson_Core_bejson_field_map";

// BEJSON validators (104, 104a, 104db)
export {
  validateDocument,
  validate104,
  validate104a,
  validate104db,
  assertValid,
  isValid,
} from "./lib_bejson_Core_bejson_validators";

// MFDB validators
export {
  discoverRole,
  validateManifest,
  validateEntityFile,
  validateDatabase,
  decodeManifestRecords,
  decodeDatabaseMeta,
} from "./lib_bejson_Core_mfdb_validators";

// MFDB core
export {
  createManifest,
  registerEntity,
  unregisterEntity,
  syncRecordCount,
} from "./lib_bejson_Core_mfdb_core";

export type { EntityValidationOptions, DatabaseValidationOptions } from "./lib_bejson_Core_mfdb_validators";
export type { CreateManifestOptions as MFDBCreateManifestOptions } from "./lib_bejson_Core_mfdb_core";

// Gaming module re-exports (relative from Core/ to Gaming/)
export * from "../Gaming/lib_bejson_Gaming_bejson_assets";
export * from "../Gaming/lib_bejson_Gaming_bejson_engine";
export * from "../Gaming/lib_bejson_Gaming_bejson_events";
export * from "../Gaming/lib_bejson_Gaming_bejson_grid";
export * from "../Gaming/lib_bejson_Gaming_bejson_input";
export * from "../Gaming/lib_bejson_Gaming_bejson_physics";
export * from "../Gaming/lib_bejson_Gaming_bejson_renderer";

// Schema management
export * from "./lib_bejson_Core_bejson_schema";
