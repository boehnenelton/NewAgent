/**
 * Library:        lib_bejson_Core_bejson_schema.ts
 * Family:         Core
 * Description:    Schema management and enforcement for TypeScript.
 * Version:        2.0.2
 * Date:           2026-05-21
 * Author:         Elton Boehnen
 * Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
 * Format_Creator: Elton Boehnen
 * RELATIONAL_ID:  990f4fa1-413c-4467-8500-40f3ef2acc17
 */

import {
  BEJSONDocument,
  BEJSONField,
  ValidationResult,
} from "./lib_bejson_Core_bejson_types";

export const BEJSONSchema = {
    /**
     * Extracts the schema (structure) from a BEJSON document.
     */
    extract(doc: BEJSONDocument): BEJSONDocument {
        const schema = JSON.parse(JSON.stringify(doc)) as BEJSONDocument;
        schema.Values = [];
        return schema;
    },

    /**
     * Validates a BEJSON document against a specific schema.
     */
    validateAgainst(doc: BEJSONDocument, schema: BEJSONDocument): ValidationResult {
        const result: ValidationResult = { valid: true, errors: [], warnings: [] };

        // 1. Version Check
        if (doc.Format_Version !== schema.Format_Version) {
            result.valid = false;
            result.errors.push({
                code: 4,
                message: `Version mismatch: Document is ${doc.Format_Version}, Schema is ${schema.Format_Version}`
            });
        }

        // 2. Records_Type Check
        if (JSON.stringify(doc.Records_Type) !== JSON.stringify(schema.Records_Type)) {
            result.valid = false;
            result.errors.push({
                code: 5,
                message: "Records_Type mismatch: Document types do not match schema types."
            });
        }

        // 3. Fields Check
        const docFields = doc.Fields || [];
        const schFields = schema.Fields || [];

        if (docFields.length !== schFields.length) {
            result.valid = false;
            result.errors.push({
                code: 9,
                message: `Field count mismatch: Document has ${docFields.length}, Schema has ${schFields.length}`
            });
        } else {
            for (let i = 0; i < docFields.length; i++) {
                const df = docFields[i] as BEJSONField;
                const sf = schFields[i] as BEJSONField;

                if (df.name !== sf.name) {
                    result.valid = false;
                    result.errors.push({
                        code: 6,
                        message: `Field name mismatch at index ${i}: expected '${sf.name}', found '${df.name}'`
                    });
                }
                if (df.type !== sf.type) {
                    result.valid = false;
                    result.errors.push({
                        code: 8,
                        message: `Field type mismatch for '${sf.name}': expected '${sf.type}', found '${df.type}'`
                    });
                }
                if (df.Record_Type_Parent !== sf.Record_Type_Parent) {
                    result.valid = false;
                    result.errors.push({
                        code: 11,
                        message: `Record_Type_Parent mismatch for '${sf.name}': expected '${sf.Record_Type_Parent}', found '${df.Record_Type_Parent}'`
                    });
                }
            }
        }

        return result;
    },

    /**
     * Returns a mapping of field names to their definitions.
     */
    getFieldMap(schema: BEJSONDocument): Record<string, BEJSONField> {
        const map: Record<string, BEJSONField> = {};
        (schema.Fields || []).forEach(f => {
            const field = f as BEJSONField;
            map[field.name] = field;
        });
        return map;
    },

    /**
     * Utility to create a schema object from scratch.
     */
    inferFromData(recordsType: string | string[], fields: any[], version: string = "104a"): BEJSONDocument {
        return {
            Format: "BEJSON",
            Format_Version: version as any,
            Format_Creator: "Elton Boehnen",
            Records_Type: Array.isArray(recordsType) ? recordsType : [recordsType],
            Fields: fields,
            Values: []
        } as BEJSONDocument;
    }
};
