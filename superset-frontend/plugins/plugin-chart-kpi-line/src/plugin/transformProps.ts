/* eslint-disable theme-colors/no-literal-colors */
import {
  DataRecord,
  DataRecordValue,
  getValueFormatter,
  t,
} from '@superset-ui/core';
import { EChartsCoreOption } from 'echarts/core';
import { KpiLineChartProps, KpiLineVizProps, SeriesDatum } from '../types';

type KpiGoalDirection = 'greater_than' | 'less_than';
const AXIS_FONT_SIZE = 15;
const AXIS_COLOR = '#000000';

function getComparison(
  current: number | null,
  target: number | null,
  goalDirection?: KpiGoalDirection,
): {
  direction: 'up' | 'down' | 'none';
  value: number;
  noData: boolean;
  isGood?: boolean;
} {
  if (current === null || target === null) {
    return { direction: 'none', value: 0, noData: true };
  }
  const diff = current - target;
  const isGood =
    goalDirection === 'less_than' ? current <= target : current >= target;

  return {
    direction: diff > 0 ? 'up' : diff < 0 ? 'down' : 'none',
    value: Math.abs(diff),
    noData: false,
    isGood,
  };
}

function safeNumber(val: DataRecordValue): number | null {
  if (val === null || val === undefined || typeof val === 'boolean')
    return null;
  const num = Number(val);
  return Number.isNaN(num) ? null : num;
}

function computeRatio(numerator: number, denominator: number): number | null {
  if (denominator <= 0) return null;
  return (numerator / denominator) * 100;
}

function getSeriesYValues(seriesList: SeriesDatum[][]): number[] {
  return seriesList
    .flat()
    .map(datum => datum[1])
    .filter(
      (value): value is number => value !== null && Number.isFinite(value),
    );
}

function getYAxisMin(seriesList: SeriesDatum[][]): number | undefined {
  const values = getSeriesYValues(seriesList);
  if (values.length === 0) return undefined;

  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const range = Math.abs(maxValue - minValue);
  const paddingBase = Math.max(
    Math.abs(minValue),
    Math.abs(maxValue),
    range,
    1,
  );

  const padding = paddingBase * 0.1;
  if (minValue >= 0) {
    return Math.max(0, minValue - padding);
  }
  return minValue - padding;
}

function getYAxisMax(seriesList: SeriesDatum[][]): number | undefined {
  const values = getSeriesYValues(seriesList);
  if (values.length === 0) return undefined;

  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const range = Math.abs(maxValue - minValue);
  const paddingBase = Math.max(
    Math.abs(minValue),
    Math.abs(maxValue),
    range,
    1,
  );

  return maxValue + paddingBase * 0.1;
}

function formatXAxisLabel(value: string): string {
  const label = String(value);
  return label.length > 18 ? `${label.slice(0, 18)}...` : label;
}
function getXAxisLabelInterval(totalTicks: number): number | ((index: number) => boolean) {
  if (totalTicks <= 10) {
    return 0;
  }

  return (index: number) => index % 2 === 0;
}


export default function transformProps(
  chartProps: KpiLineChartProps,
): KpiLineVizProps {
  const {
    width,
    height,
    queriesData,
    formData,
    hooks,
    datasource: { currencyFormats = {}, columnFormats = {} },
  } = chartProps;

  const {
    kpiTitle = '',
    detailUrl = '',
    kpiGroup = 'none',
    kpiGoalDirection = 'greater_than',
    bigNumberUnit = '',
    xAxisTitle = '',
    zoomable = false,
    yAxisFormat,
    currencyFormat,
  } = formData;

  const { data = [], colnames = [] } = queriesData[0] || {};

  const isThreeMetric = colnames.length >= 4 && colnames.length < 6;

  const resolvedBigNumberUnit =
    (bigNumberUnit || '').trim() || (isThreeMetric ? '' : '%');

  const xIdx = 0;
  const kpiIdx = 1;
  const curIdx = 2;
  const curTotIdx = isThreeMetric ? -1 : 3;
  const prevIdx = isThreeMetric ? 3 : 4;
  const prevTotIdx = isThreeMetric ? -1 : 5;

  const rows = data as DataRecord[];

  const kpiRow = rows.length > 0 ? rows[0] : null;

  const extractVal = (row: DataRecord | null, idx: number): number | null => {
    if (!row || idx < 0 || idx >= colnames.length) return null;
    return safeNumber(row[colnames[idx]]);
  };

  const kpiVal = extractVal(kpiRow, kpiIdx);

  let currentRatio: number | null;
  let prevRatio: number | null;
  let currentAbsolute: string;

  if (isThreeMetric) {
    const curVal = extractVal(kpiRow, curIdx);
    const prevVal = extractVal(kpiRow, prevIdx);
    currentRatio = curVal;
    prevRatio = prevVal;
    currentAbsolute =
      currentRatio !== null
        ? `${currentRatio.toFixed(2)}${resolvedBigNumberUnit}`
        : 'N/A';
  } else {
    const curSuccVal = extractVal(kpiRow, curIdx);
    const curTotVal = extractVal(kpiRow, curTotIdx);
    const prevSuccVal = extractVal(kpiRow, prevIdx);
    const prevTotVal = extractVal(kpiRow, prevTotIdx);
    currentRatio = computeRatio(curSuccVal ?? 0, curTotVal ?? 0);
    prevRatio = computeRatio(prevSuccVal ?? 0, prevTotVal ?? 0);
    currentAbsolute =
      currentRatio !== null
        ? `${(curSuccVal ?? 0).toLocaleString()}/${(
            curTotVal ?? 0
          ).toLocaleString()}`
        : 'N/A';
  }

  const chartRows = rows.slice(1);
  const avgKpi = kpiVal;

  const kpiSeries: SeriesDatum[] = [];
  const currentSeries: SeriesDatum[] = [];
  const prevSeries: SeriesDatum[] = [];
  const xAxisLabels: string[] = [];

  chartRows.forEach(row => {
    const xVal = xIdx >= 0 ? row[colnames[xIdx]] : null;
    if (xVal === null || xVal === undefined) return;
    const x = String(xVal);
    xAxisLabels.push(x);

    if (kpiIdx >= 0) {
      const kval = extractVal(row, kpiIdx);
      if (kval !== null) {
        kpiSeries.push([x, kval]);
      }
    }

    if (isThreeMetric) {
      const cur = extractVal(row, curIdx);
      if (cur !== null) {
        currentSeries.push([x, cur]);
      }
      const prev = extractVal(row, prevIdx);
      if (prev !== null) {
        prevSeries.push([x, prev]);
      }
    } else {
      const succ = safeNumber(row[colnames[curIdx]]) ?? 0;
      const tot = safeNumber(row[colnames[curTotIdx]]) ?? 0;
      const ratio = computeRatio(succ, tot);
      if (ratio !== null) {
        currentSeries.push([x, ratio, succ, tot]);
      }
      const pSucc = safeNumber(row[colnames[prevIdx]]) ?? 0;
      const pTot = safeNumber(row[colnames[prevTotIdx]]) ?? 0;
      const pRatio = computeRatio(pSucc, pTot);
      if (pRatio !== null) {
        prevSeries.push([x, pRatio, pSucc, pTot]);
      }
    }
  });

  const kpiComparison = getComparison(currentRatio, avgKpi, kpiGoalDirection);
  const prevPeriodComparison = getComparison(
    currentRatio,
    prevRatio,
    kpiGoalDirection,
  );

  const numberFormatter = getValueFormatter(
    '',
    currencyFormats,
    columnFormats,
    yAxisFormat,
    currencyFormat,
  );

  const allXValues = [
    ...kpiSeries.map(d => d[0]),
    ...currentSeries.map(d => d[0]),
    ...prevSeries.map(d => d[0]),
  ];
  const firstX = allXValues.length > 0 ? allXValues[0] : '';
  const lastX = allXValues.length > 0 ? allXValues[allXValues.length - 1] : '';
  const firstKpiPoint = kpiSeries.find(datum => datum[1] !== null);
  const yAxisMin = getYAxisMin([kpiSeries, currentSeries, prevSeries]);
  const yAxisMax = getYAxisMax([kpiSeries, currentSeries, prevSeries]);

  const series: any[] = [
    {
      name: t('Kỳ này'),
      type: 'line',
      data: currentSeries,
      z: 3,
      smooth: false,
      symbol: 'circle',
      symbolSize: 5,
      showSymbol: true,
      lineStyle: { width: 2 },
      clip: true,
      itemStyle: { color: '#E04343' },
      label: {
        show: true,
        position: 'top',
        color: '#E04343',
        fontSize: 15,
        formatter: (p: any) => {
          const value = p.data?.[1];
          if (value === null) {
            return '';
          }

          const shouldShowLabel =
            xAxisLabels.length <= 10 ? true : p.dataIndex % 2 === 0;
          return shouldShowLabel ? Number(value).toFixed(2) : '';
        },
      },
      emphasis: {
        label: { show: true },
      },
    },
  ];

  if (prevSeries.length > 0) {
    series.push({
      name: t('Kỳ trước'),
      type: 'line',
      data: prevSeries,
      z: 2,
      smooth: false,
      symbol: 'circle',
      symbolSize: 5,
      showSymbol: true,
      lineStyle: { width: 2 },
      clip: true,
      itemStyle: { color: '#A0A0A0' },
    });
  }

  if (kpiSeries.length > 0) {
    series.push({
      name: t('KPI'),
      type: 'line',
      data: kpiSeries,
      z: 1,
      smooth: false,
      symbol: 'circle',
      symbolSize: 4,
      showSymbol: false,
      lineStyle: { type: 'solid', width: 1, color: '#2CA02C' },
      clip: true,
      itemStyle: { color: '#2CA02C' },
      markPoint: firstKpiPoint
        ? {
            symbol: 'circle',
            symbolSize: 1,
            itemStyle: { color: 'transparent', opacity: 0 },
            label: {
              show: true,
              position: 'right',
              color: '#2CA02C',
              fontSize: 15,
              fontWeight: 600,
              formatter: () => Number(firstKpiPoint[1]).toFixed(2),
              offset: [8, 0],
            },
            data: [
              {
                coord: [firstKpiPoint[0], firstKpiPoint[1]],
              },
            ],
          }
        : undefined,
    });
  }

  const echartOptions: EChartsCoreOption = {
    series,
    textStyle: {
      fontSize: AXIS_FONT_SIZE,
    },
    xAxis: {
      type: 'category',
      data: xAxisLabels,
      boundaryGap: ['2%', '2%'],
      name: xAxisTitle || undefined,
      nameLocation: 'middle',
      nameGap: 30,
      nameTextStyle: {
        fontSize: AXIS_FONT_SIZE,
        color: AXIS_COLOR,
      },
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      axisTick: {
        alignWithLabel: true,
        interval: 0,
        lineStyle: { color: AXIS_COLOR },
      },
      axisLabel: {
        align: 'center',
        color: AXIS_COLOR,
        fontSize: AXIS_FONT_SIZE,
        formatter: formatXAxisLabel,
        hideOverlap: true,
        interval: getXAxisLabelInterval(xAxisLabels.length),
        margin: 12,
        overflow: 'truncate',
        rotate: 0,
        width: 90,
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      axisTick: { lineStyle: { color: AXIS_COLOR } },
      min: yAxisMin,
      max: yAxisMax,
      name: undefined,
      axisLabel: {
        show: false,
      },
      splitLine: { show: false },
    },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        if (!Array.isArray(params)) return '';
        let html = `${params[0].name}<br/>`;
        params.forEach((p: any) => {
          const value = p.data[1];
          const val = value !== null ? Number(value).toFixed(2) : 'N/A';
          if (isThreeMetric) {
            html += `${p.marker} ${p.seriesName}: ${val}<br/>`;
          } else {
            const raw =
              p.data[2] !== undefined && p.data[3] !== undefined
                ? ` (${Number(p.data[2]).toLocaleString()} / ${Number(
                    p.data[3],
                  ).toLocaleString()})`
                : '';
            html += `${p.marker} ${p.seriesName}: ${val}%${raw}<br/>`;
          }
        });
        return html;
      },
    },
    legend: {
      show: false,
    },
    grid: {
      left: 8,
      right: 8,
      top: 20,
      bottom: 17,
      containLabel: true,
    },
    toolbox: zoomable
      ? {
          show: true,
          feature: {
            dataZoom: { yAxisIndex: 'none' },
          },
        }
      : undefined,
    dataZoom: zoomable
      ? [{ type: 'slider', start: 0, end: 100 }, { type: 'inside' }]
      : undefined,
  };

  const { onContextMenu } = hooks;

  return {
    width,
    height,
    kpiTitle,
    detailUrl,
    kpiGroup,
    currentRatio,
    currentAbsolute,
    prevRatio,
    kpiTarget: avgKpi,
    bigNumberUnit: resolvedBigNumberUnit,
    kpiComparison,
    prevPeriodComparison,
    currentSeries,
    prevSeries,
    kpiTargetSeries:
      kpiSeries.length > 0
        ? [
            [firstX, kpiSeries[0][1]],
            [lastX, kpiSeries[kpiSeries.length - 1][1]],
          ]
        : [],
    echartOptions,
    formData,
    onContextMenu,
    numberFormatter,
  };
}
