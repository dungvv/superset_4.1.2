/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

/**
 * Frontend (4.x) in-memory metadata is not fully valid for Superset 3.1.x
 * DashboardJSONMetadataSchema.validate. Always run this before PUT/POST
 * json_metadata.
 *
 * 3.1.3 rejects:
 * - map_label_colors (Unknown field)
 * - shared_label_colors as string[] (must be Dict)
 * - any other unknown top-level keys
 */

// Keys accepted by Apache Superset 3.1.3 DashboardJSONMetadataSchema
const DASHBOARD_METADATA_KEYS_3_1 = new Set([
  'native_filter_configuration',
  'chart_configuration',
  'global_chart_configuration',
  'filter_sets_configuration',
  'timed_refresh_immune_slices',
  'filter_scopes',
  'expanded_slices',
  'refresh_frequency',
  'default_filters',
  'stagger_refresh',
  'stagger_time',
  'color_scheme',
  'color_namespace',
  'positions',
  'label_colors',
  'shared_label_colors',
  'color_scheme_domain',
  'cross_filters_enabled',
  'import_time',
  'remote_id',
  'filter_bar_orientation',
  'native_filter_migration',
]);

export function sanitizeDashboardMetadataForSave(
  metadata: Record<string, unknown> | null | undefined = {},
): Record<string, unknown> {
  const raw = metadata && typeof metadata === 'object' ? metadata : {};
  const mapLabelColors = raw.map_label_colors;
  let shared = raw.shared_label_colors as unknown;

  if (Array.isArray(shared)) {
    const colorMap =
      mapLabelColors &&
      typeof mapLabelColors === 'object' &&
      !Array.isArray(mapLabelColors)
        ? (mapLabelColors as Record<string, string>)
        : {};
    shared = Object.fromEntries(
      (shared as unknown[])
        .filter(
          (label): label is string =>
            typeof label === 'string' && Boolean(colorMap[label]),
        )
        .map(label => [label, colorMap[label]]),
    );
  } else if (
    !shared ||
    typeof shared !== 'object' ||
    Array.isArray(shared)
  ) {
    shared = {};
  }

  const out: Record<string, unknown> = {};
  Object.keys(raw).forEach(key => {
    if (
      key === 'map_label_colors' ||
      key === 'show_native_filters' ||
      !DASHBOARD_METADATA_KEYS_3_1.has(key)
    ) {
      return;
    }
    out[key] = raw[key];
  });
  out.shared_label_colors = shared;
  // Defense in depth if something re-spread the keys later
  delete out.map_label_colors;
  delete out.show_native_filters;

  return out;
}

/** Stringify for API body after sanitizing. */
export function stringifyDashboardMetadataForSave(
  metadata: Record<string, unknown> | null | undefined = {},
): string {
  return JSON.stringify(sanitizeDashboardMetadataForSave(metadata));
}
