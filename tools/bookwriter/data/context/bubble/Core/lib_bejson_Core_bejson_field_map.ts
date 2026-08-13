/**
 * Library:        lib_bejson_Core_bejson_field_map.ts
 * Family:         Core
 * Description:    TypeScript implementation of the Field Map Cache.
 * Version:        2.1.1
 * Date:           2026-06-02
 * Author:         Elton Boehnen
 * Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
 * Format_Creator: Elton Boehnen
 * RELATIONAL_ID:  cda1bc88-4de3-4ef6-bb0e-af6212453eaf
 */

import { BEJSONDocument } from './lib_bejson_Core_bejson_types';

/**
 * Field Map type: mapping of field name to its positional index.
 */
export type FieldMap = { [key: string]: number };

/**
 * Internal global cache for FieldMaps.
 */
const _FIELD_MAP_CACHE: Map<string, FieldMap> = new Map();

/**
 * Generates a mapping of field names to their indices for a BEJSON document.
 * Utilizes a global cache to speed up repeated access to similar structures.
 */
export function bejson_core_get_field_map(doc: BEJSONDocument): FieldMap {
    if (!doc || !doc.Fields) return {};
    
    const fieldNames = doc.Fields.map(f => f.name);
    const cacheKey = (doc.Format_Version || '104') + ':' + fieldNames.join(',');
    
    const cached = _FIELD_MAP_CACHE.get(cacheKey);
    if (cached) return cached;
    
    const fieldMap: FieldMap = {};
    doc.Fields.forEach((f, i) => {
        fieldMap[f.name] = i;
    });
    
    _FIELD_MAP_CACHE.set(cacheKey, fieldMap);
    return fieldMap;
}

/**
 * Returns the index of a specific field by name, using the cache.
 */
export function bejson_core_get_field_index(doc: BEJSONDocument, fieldName: string): number {
    const fieldMap = bejson_core_get_field_map(doc);
    const idx = fieldMap[fieldName];
    return (idx !== undefined) ? idx : -1;
}

/**
 * Clears the internal field map cache.
 */
export function bejson_core_clear_field_map_cache(): void {
    _FIELD_MAP_CACHE.clear();
}
