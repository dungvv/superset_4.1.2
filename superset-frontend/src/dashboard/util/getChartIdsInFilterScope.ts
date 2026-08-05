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
import { NativeFilterScope } from '@superset-ui/core';
import { CHART_TYPE } from './componentTypes';
import { Layout } from '../types';

export function getChartIdsInFilterScope(
  filterScope: NativeFilterScope,
  chartIds: number[],
  layout: Layout,
) {
  const layoutItems = Object.values(layout);
  // Coerce ids — metadata sometimes stores excluded as strings, which makes
  // includes() miss and leave charts incorrectly in filter scope.
  const excluded = new Set((filterScope.excluded ?? []).map(Number));
  const rootPath = new Set(filterScope.rootPath ?? []);
  return chartIds
    .map(Number)
    .filter(
      chartId =>
        !excluded.has(chartId) &&
        layoutItems
          .find(
            layoutItem =>
              layoutItem?.type === CHART_TYPE &&
              Number(layoutItem.meta?.chartId) === chartId,
          )
          ?.parents?.some(elementId => rootPath.has(elementId)),
    );
}
