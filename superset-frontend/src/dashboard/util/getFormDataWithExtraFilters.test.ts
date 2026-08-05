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
import getFormDataWithExtraFilters, {
  GetFormDataWithExtraFiltersArguments,
} from 'src/dashboard/util/charts/getFormDataWithExtraFilters';
import { sliceId as chartId } from 'spec/fixtures/mockChartQueries';

describe('getFormDataWithExtraFilters', () => {
  const filterId = 'native-filter-1';
  const mockChart = {
    id: chartId,
    chartAlert: null,
    chartStatus: null,
    chartUpdateEndTime: null,
    chartUpdateStartTime: 1,
    lastRendered: 1,
    latestQueryFormData: {},
    sliceFormData: null,
    queryController: null,
    queriesResponse: null,
    triggerQuery: false,
    form_data: {
      viz_type: 'filter_select',
      filters: [
        {
          col: 'country_name',
          op: 'IN',
          val: ['United States'],
        },
      ],
      datasource: '123',
      url_params: {},
    },
  };
  const mockArgs: GetFormDataWithExtraFiltersArguments = {
    chartConfiguration: {},
    chart: mockChart,
    filters: {
      region: ['Spain'],
      color: ['pink', 'purple'],
    },
    sliceId: chartId,
    nativeFilters: {},
    dataMask: {
      [filterId]: {
        id: filterId,
        extraFormData: {},
        filterState: {},
        ownState: {},
      },
    },
    extraControls: {
      stack: 'Stacked',
    },
    allSliceIds: [chartId],
  };

  it('should include filters from the passed filters', () => {
    const result = getFormDataWithExtraFilters(mockArgs);
    expect(result.extra_filters).toHaveLength(2);
    expect(result.extra_filters[0]).toEqual({
      col: 'region',
      op: 'IN',
      val: ['Spain'],
    });
    expect(result.extra_filters[1]).toEqual({
      col: 'color',
      op: 'IN',
      val: ['pink', 'purple'],
    });
  });

  it('should compose extra control', () => {
    const result = getFormDataWithExtraFilters(mockArgs);
    expect(result.stack).toEqual('Stacked');
  });

  it('should only apply in-scope Time filters (not out-of-scope ones)', () => {
    const timeFilterA = 'NATIVE_FILTER-time-a';
    const timeFilterB = 'NATIVE_FILTER-time-b';
    const chartAId = chartId;
    const chartBId = chartId + 1;

    const result = getFormDataWithExtraFilters({
      ...mockArgs,
      chart: { ...mockChart, id: chartAId },
      sliceId: chartAId,
      allSliceIds: [chartAId, chartBId],
      nativeFilters: {
        [timeFilterA]: {
          id: timeFilterA,
          filterType: 'filter_time',
          chartsInScope: [chartAId],
          targets: [],
        },
        [timeFilterB]: {
          id: timeFilterB,
          filterType: 'filter_time',
          chartsInScope: [chartBId],
          targets: [],
        },
      },
      dataMask: {
        [timeFilterA]: {
          id: timeFilterA,
          extraFormData: { time_range: 'Last week' },
          filterState: { value: 'Last week' },
          ownState: {},
        },
        [timeFilterB]: {
          id: timeFilterB,
          extraFormData: { time_range: 'Last month' },
          filterState: { value: 'Last month' },
          ownState: {},
        },
      },
    });

    expect(result.extra_form_data).toEqual({ time_range: 'Last week' });
  });

  it('should ignore stale chartsInScope when ROOT scope excludes a chart', () => {
    // Real bug: metadata chartsInScope still lists chart 3 after user
    // scoped Last day to chart 1 only (excluded = [2, 3]).
    const timeFilterA = 'NATIVE_FILTER-time-day';
    const chartAId = chartId;
    const chartBId = chartId + 1;
    const chartCId = chartId + 2;

    const result = getFormDataWithExtraFilters({
      ...mockArgs,
      chart: { ...mockChart, id: chartCId },
      sliceId: chartCId,
      allSliceIds: [chartAId, chartBId, chartCId],
      nativeFilters: {
        [timeFilterA]: {
          id: timeFilterA,
          filterType: 'filter_time',
          // stale: still lists all charts
          chartsInScope: [chartAId, chartBId, chartCId],
          scope: {
            rootPath: ['ROOT_ID'],
            excluded: [chartBId, chartCId],
          },
          targets: [],
        },
      },
      dataMask: {
        [timeFilterA]: {
          id: timeFilterA,
          extraFormData: { time_range: 'Last day' },
          filterState: { value: 'Last day' },
          ownState: {},
        },
      },
    });

    expect(result.extra_form_data).toBeUndefined();
  });

  it('should apply Last day only to charts not in excluded list', () => {
    const timeFilterA = 'NATIVE_FILTER-time-day';
    const chartAId = chartId;
    const chartBId = chartId + 1;
    const chartCId = chartId + 2;

    const inScope = getFormDataWithExtraFilters({
      ...mockArgs,
      chart: { ...mockChart, id: chartAId },
      sliceId: chartAId,
      allSliceIds: [chartAId, chartBId, chartCId],
      nativeFilters: {
        [timeFilterA]: {
          id: timeFilterA,
          filterType: 'filter_time',
          chartsInScope: [chartAId],
          scope: {
            rootPath: ['ROOT_ID'],
            excluded: [chartBId, chartCId],
          },
          targets: [],
        },
      },
      dataMask: {
        [timeFilterA]: {
          id: timeFilterA,
          extraFormData: { time_range: 'Last day' },
          filterState: { value: 'Last day' },
          ownState: {},
        },
      },
    });
    expect(inScope.extra_form_data).toEqual({ time_range: 'Last day' });
  });

  it('should not apply out-of-scope Time filter to a chart', () => {
    const timeFilterB = 'NATIVE_FILTER-time-b';
    const chartAId = chartId;
    const chartBId = chartId + 1;

    const result = getFormDataWithExtraFilters({
      ...mockArgs,
      chart: { ...mockChart, id: chartAId },
      sliceId: chartAId,
      allSliceIds: [chartAId, chartBId],
      nativeFilters: {
        [timeFilterB]: {
          id: timeFilterB,
          filterType: 'filter_time',
          chartsInScope: [chartBId],
          targets: [],
        },
      },
      dataMask: {
        [timeFilterB]: {
          id: timeFilterB,
          extraFormData: { time_range: 'Last month' },
          filterState: { value: 'Last month' },
          ownState: {},
        },
      },
    });

    expect(result.extra_form_data).toBeUndefined();
  });

  it('should only apply in-scope Value filters (not out-of-scope ones)', () => {
    const valueFilterA = 'NATIVE_FILTER-value-a';
    const valueFilterB = 'NATIVE_FILTER-value-b';
    const chartAId = chartId;
    const chartBId = chartId + 1;

    const result = getFormDataWithExtraFilters({
      ...mockArgs,
      chart: { ...mockChart, id: chartAId },
      sliceId: chartAId,
      allSliceIds: [chartAId, chartBId],
      nativeFilters: {
        [valueFilterA]: {
          id: valueFilterA,
          filterType: 'filter_select',
          chartsInScope: [chartAId],
          targets: [{ column: { name: 'country' } }],
        },
        [valueFilterB]: {
          id: valueFilterB,
          filterType: 'filter_select',
          chartsInScope: [chartBId],
          targets: [{ column: { name: 'region' } }],
        },
      },
      dataMask: {
        [valueFilterA]: {
          id: valueFilterA,
          extraFormData: {
            filters: [{ col: 'country', op: 'IN', val: ['USA'] }],
          },
          filterState: { value: ['USA'] },
          ownState: {},
        },
        [valueFilterB]: {
          id: valueFilterB,
          extraFormData: {
            filters: [{ col: 'region', op: 'IN', val: ['West'] }],
          },
          filterState: { value: ['West'] },
          ownState: {},
        },
      },
    });

    expect(result.extra_form_data).toEqual({
      filters: [{ col: 'country', op: 'IN', val: ['USA'] }],
    });
  });

  it('should only apply in-scope Time grain filters (override fields)', () => {
    const grainFilterA = 'NATIVE_FILTER-grain-a';
    const grainFilterB = 'NATIVE_FILTER-grain-b';
    const chartAId = chartId;
    const chartBId = chartId + 1;

    const result = getFormDataWithExtraFilters({
      ...mockArgs,
      chart: { ...mockChart, id: chartAId },
      sliceId: chartAId,
      allSliceIds: [chartAId, chartBId],
      nativeFilters: {
        [grainFilterA]: {
          id: grainFilterA,
          filterType: 'filter_timegrain',
          chartsInScope: [chartAId],
          targets: [],
        },
        [grainFilterB]: {
          id: grainFilterB,
          filterType: 'filter_timegrain',
          chartsInScope: [chartBId],
          targets: [],
        },
      },
      dataMask: {
        [grainFilterA]: {
          id: grainFilterA,
          extraFormData: { time_grain_sqla: 'P1D' },
          filterState: { value: 'P1D' },
          ownState: {},
        },
        [grainFilterB]: {
          id: grainFilterB,
          extraFormData: { time_grain_sqla: 'P1W' },
          filterState: { value: 'P1W' },
          ownState: {},
        },
      },
    });

    expect(result.extra_form_data).toEqual({ time_grain_sqla: 'P1D' });
  });
});
