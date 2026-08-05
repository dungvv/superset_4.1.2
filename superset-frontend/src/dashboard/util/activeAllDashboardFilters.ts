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
import {
  DataMaskStateWithId,
  Filter,
  PartialFilters,
  JsonObject,
  NativeFilterScope,
} from '@superset-ui/core';
import { ActiveFilters, ChartConfiguration } from '../types';
import { DASHBOARD_ROOT_ID } from './constants';

export const getRelevantDataMask = (
  dataMask: DataMaskStateWithId,
  prop: string,
): JsonObject | DataMaskStateWithId =>
  Object.values(dataMask)
    .filter(item => item[prop])
    .reduce(
      (prev, next) => ({ ...prev, [next.id]: prop ? next[prop] : next }),
      {},
    );

const toChartId = (id: string | number): number => Number(id);

/**
 * Resolve which charts a native filter applies to.
 * Prefer live scope.excluded (authoritative when rootPath is ROOT) so we do not
 * keep a stale chartsInScope that still lists charts the user unchecked —
 * that bug makes "no filter on chart 3" still receive a Time filter.
 */
export const resolveNativeFilterChartsInScope = (
  nativeFilter: Pick<Filter, 'chartsInScope' | 'scope'>,
  allSliceIds: number[],
): number[] => {
  const allIds = (allSliceIds ?? []).map(toChartId);
  const scope = nativeFilter.scope as NativeFilterScope | undefined;
  const rootPath = scope?.rootPath ?? [];
  const excluded = new Set((scope?.excluded ?? []).map(toChartId));

  // Dashboard-wide root: recompute from excluded every time.
  // Covers charts added after the filter was saved (not in excluded) AND
  // charts the user excluded while chartsInScope metadata lagged behind.
  if (rootPath.length === 1 && rootPath[0] === DASHBOARD_ROOT_ID) {
    return allIds.filter(id => !excluded.has(id));
  }

  // Tab / partial layout scope still needs chartsInScope (needs layout tree).
  if (nativeFilter.chartsInScope != null) {
    return nativeFilter.chartsInScope.map(toChartId);
  }

  // Not computed yet and not a global root — apply to none until layout runs.
  return [];
};

const isInScope = (scope: number[], chartId: number | string): boolean =>
  scope.some(id => toChartId(id) === toChartId(chartId));

export { isInScope };

export const getAllActiveFilters = ({
  chartConfiguration,
  nativeFilters,
  dataMask,
  allSliceIds,
}: {
  chartConfiguration: ChartConfiguration;
  dataMask: DataMaskStateWithId;
  nativeFilters: PartialFilters;
  allSliceIds: number[];
}): ActiveFilters => {
  const activeFilters: ActiveFilters = {};

  // Combine native filters with cross filters, because they have similar logic
  Object.values(dataMask).forEach(({ id: filterId, extraFormData }) => {
    const nativeFilter = nativeFilters?.[filterId] as Filter | undefined;
    if (nativeFilter) {
      activeFilters[filterId] = {
        scope: resolveNativeFilterChartsInScope(nativeFilter, allSliceIds),
        filterType: nativeFilter.filterType,
        targets: nativeFilter.targets ?? [],
        values: extraFormData,
      };
      return;
    }

    const crossFilters = chartConfiguration?.[filterId]?.crossFilters;
    // Only chart keys that are cross-filter sources — never promote every
    // dataMask chart entry with fallback allSliceIds (that ignored scoping).
    if (crossFilters) {
      activeFilters[filterId] = {
        scope: (crossFilters.chartsInScope ?? allSliceIds ?? []).map(
          toChartId,
        ),
        filterType: undefined,
        targets: crossFilters.chartsInScope ?? allSliceIds ?? [],
        values: extraFormData,
      };
    }
  });
  return activeFilters;
};
