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
  const diff = Number((current - target).toFixed(2));
  // (unchanged: internal, not displayed)
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

// vi-VN: decimal ',', thousands '.'.
const VI = 'vi-VN';
function fmtRatio(value: number): string {
  return value.toLocaleString(VI, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
function fmtRatioTrimTrailingZero(value: number): string {
  const formatted = fmtRatio(value);
  if (formatted === '100,00') return '100,0';
  return formatted;
}
function fmtInt(value: number): string {
  return value.toLocaleString(VI);
}

// Null total = missing data (null). Real zero total = no attempts, nothing
// failed (100). Coercing null->0 upstream would conflate the two.
function computeRatio(
  numerator: number | null,
  denominator: number | null,
): number | null {
  if (denominator === null) return null;
  if (denominator <= 0) return 100;
  const num = numerator ?? 0;
  // Round to 2dp at source so display, tooltip, and comparisons agree.
  const ratio = Number(((num / denominator) * 100).toFixed(2));
  // A real gap (num < den) must never read as 100%, even when rounding says so
  // (999999/1000000 -> 99.99, not 100). Only num >= den is a true 100%.
  return ratio >= 100 && num < denominator ? 99.99 : ratio;
}

function getSeriesYValues(seriesList: SeriesDatum[][]): number[] {
  return seriesList
    .flat()
    .map(datum => datum[1])
    .filter(
      (value): value is number => value !== null && Number.isFinite(value),
    );
}

// Padding is driven by the data's RANGE, not its magnitude: for percentage
// metrics |max| dwarfs the range, so scaling by magnitude flattened the lines
// into ~9% of the chart height. The extra headroom on top leaves room for the
// point labels, which sit above the line.
function getYAxisBounds(seriesList: SeriesDatum[][]): {
  min: number | undefined;
  max: number | undefined;
} {
  const values = getSeriesYValues(seriesList);
  if (values.length === 0) return { min: undefined, max: undefined };

  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  // The relative and absolute floors keep near-flat data from collapsing to a
  // zero-height axis, which ECharts cannot draw.
  const padding = Math.max(
    (maxValue - minValue) * 0.18,
    Math.abs(maxValue) * 0.005,
    0.25,
  );

  return {
    min: minValue >= 0 ? Math.max(0, minValue - padding) : minValue - padding,
    max: maxValue + padding * 2,
  };
}

function formatXAxisLabel(value: string): string {
  const label = String(value);
  // If the label contains a space, only show the part before the first space
  const spaceIdx = label.indexOf(' ');
  if (spaceIdx > 0) return label.slice(0, spaceIdx);
  return label.length > 18 ? `${label.slice(0, 18)}...` : label;
}
function getXAxisLabelInterval(totalLabels: number): number {
  return totalLabels > 12 ? 2 : 0;
}

// Show every (step+1)th label counted from the LAST value so max is always
// shown, mirroring getXAxisLabelInterval's step but anchored at the end.
function getXAxisLabelIntervalFn(
  totalLabels: number,
): (index: number) => boolean {
  const step = getXAxisLabelInterval(totalLabels) + 1;
  const last = totalLabels - 1;
  return (index: number) => (last - index) % step === 0;
}

// Parse date strings in formats: dd/mm, mm/yyyy, qq/yyyy (quarter)
// Returns timestamp for sorting, or null if unparseable
function parseDateLabel(label: string): number | null {
  const trimmed = label.trim();
  const parts = trimmed.split(/[\/\-\.]/);

  if (parts.length !== 2) return null;

  const [first, second] = parts;
  const firstNum = parseInt(first, 10);
  const secondNum = parseInt(second, 10);

  // Check for quarter format: Q1/2024, q2/24, 1/2024 (quarter)
  const quarterMatch = trimmed.match(/^[Qq]?(\d)\s*[\/\-\.]\s*(\d{2,4})$/);
  if (quarterMatch) {
    const quarter = parseInt(quarterMatch[1], 10);
    let year = parseInt(quarterMatch[2], 10);
    if (year < 100) year += 2000;
    if (quarter >= 1 && quarter <= 4) {
      return new Date(year, (quarter - 1) * 3, 1).getTime();
    }
  }

  // mm/yyyy format (4-digit year)
  if (second.length === 4 && firstNum >= 1 && firstNum <= 12) {
    return new Date(secondNum, firstNum - 1, 1).getTime();
  }

  // dd/mm format (2-digit month)
  if (firstNum >= 1 && firstNum <= 31 && secondNum >= 1 && secondNum <= 12) {
    // Assume current year for dd/mm
    const year = new Date().getFullYear();
    return new Date(year, secondNum - 1, firstNum).getTime();
  }

  return null;
}

// Sort xAxisLabels and series data chronologically
function sortByTime(
  xAxisLabels: string[],
  currentSeries: SeriesDatum[],
  prevSeries: SeriesDatum[],
): void {
  if (xAxisLabels.length <= 1) return;

  // Parse all labels and check if all are parseable
  const parsed = xAxisLabels.map(label => ({
    label,
    time: parseDateLabel(label),
  }));

  const allParseable = parsed.every(item => item.time !== null);
  if (!allParseable) return;

  // Sort by timestamp
  parsed.sort((a, b) => (a.time as number) - (b.time as number));

  // Build sorted labels
  const sortedLabels = parsed.map(item => item.label);

  // Build label -> sorted index map
  const labelOrder = new Map<string, number>();
  sortedLabels.forEach((label, idx) => labelOrder.set(label, idx));

  // Sort series by label order
  const sortSeries = (series: SeriesDatum[]) => {
    series.sort((a, b) => {
      const orderA = labelOrder.get(a[0]) ?? 0;
      const orderB = labelOrder.get(b[0]) ?? 0;
      return orderA - orderB;
    });
  };

  // Update xAxisLabels in place
  xAxisLabels.length = 0;
  sortedLabels.forEach(label => xAxisLabels.push(label));

  // Sort series data
  sortSeries(currentSeries);
  sortSeries(prevSeries);
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

  const xIdx = 0;
  const metricColnames = colnames.filter((_, i) => i !== xIdx);

  const isThreeMetric = metricColnames.length === 3;

  const resolvedBigNumberUnit =
    (bigNumberUnit || '').trim() || (isThreeMetric ? '' : '%');

  const kpiIdx = 0;
  const curIdx = 1;
  const curTotIdx = isThreeMetric ? -1 : 2;
  const prevIdx = isThreeMetric ? 2 : 3;
  const prevTotIdx = isThreeMetric ? -1 : 4;

  const rows = data as DataRecord[];

  const kpiRow = rows.length > 0 ? rows[0] : null;

  const extractVal = (row: DataRecord | null, idx: number): number | null => {
    if (!row || idx < 0 || idx >= metricColnames.length) return null;
    return safeNumber(row[metricColnames[idx]]);
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
        ? `${fmtRatio(currentRatio)}${resolvedBigNumberUnit}`
        : 'N/A';
  } else {
    const curSuccVal = extractVal(kpiRow, curIdx);
    const curTotVal = extractVal(kpiRow, curTotIdx);
    const prevSuccVal = extractVal(kpiRow, prevIdx);
    const prevTotVal = extractVal(kpiRow, prevTotIdx);
    currentRatio = computeRatio(curSuccVal, curTotVal);
    prevRatio = computeRatio(prevSuccVal, prevTotVal);
    currentAbsolute =
      currentRatio !== null
        ? `${fmtInt(curSuccVal ?? 0)}/${fmtInt(curTotVal ?? 0)}`
        : 'N/A';
  }

  const avgKpi = kpiVal;

  // rows[0] is the KPI/current-period summary, rows[1] the month-to-date
  // figures; neither is a point on the line, so the series start at rows[2].
  const monthToDateRow = rows.length > 1 ? rows[1] : null;
  const chartRows = rows.slice(2);
  const monthToDateRatio = monthToDateRow
    ? isThreeMetric
      ? extractVal(monthToDateRow, curIdx)
      : (() => {
        const s = extractVal(monthToDateRow, curIdx);
        const t = extractVal(monthToDateRow, curTotIdx);
        // Both null = SQL blanked the MTD row (grain not week/custom).
        // Only floor to 100 when the row actually carries data.
        return s === null && t === null ? null : computeRatio(s, t);
      })()
    : null;

  const currentSeries: SeriesDatum[] = [];
  const prevSeries: SeriesDatum[] = [];
  const xAxisLabels: string[] = [];

  chartRows.forEach(row => {
    const xVal = xIdx >= 0 ? row[colnames[xIdx]] : null;
    if (xVal === null || xVal === undefined) return;
    const x = String(xVal);
    xAxisLabels.push(x);

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
      const succ = safeNumber(row[metricColnames[curIdx]]) ?? 0;
      const tot = safeNumber(row[metricColnames[curTotIdx]]) ?? 0;
      const ratio = computeRatio(succ, tot);
      if (ratio !== null) {
        currentSeries.push([x, ratio, succ, tot]);
      }
      const pSucc = safeNumber(row[metricColnames[prevIdx]]) ?? 0;
      const pTot = safeNumber(row[metricColnames[prevTotIdx]]) ?? 0;
      const pRatio = computeRatio(pSucc, pTot);
      if (pRatio !== null) {
        prevSeries.push([x, pRatio, pSucc, pTot]);
      }
    }
  });

  sortByTime(xAxisLabels, currentSeries, prevSeries);

  const kpiComparison = getComparison(currentRatio, avgKpi, kpiGoalDirection);
  const prevPeriodComparison = getComparison(
    currentRatio,
    prevRatio,
    kpiGoalDirection,
  );
  const monthToDateComparison = getComparison(
    monthToDateRatio,
    avgKpi,
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
    ...currentSeries.map(d => d[0]),
    ...prevSeries.map(d => d[0]),
  ];
  const firstX = allXValues.length > 0 ? allXValues[0] : '';
  const lastX = allXValues.length > 0 ? allXValues[allXValues.length - 1] : '';
  const boundsInput: SeriesDatum[][] = [currentSeries, prevSeries];
  if (avgKpi !== null && xAxisLabels.length > 0) {
    boundsInput.push([
      [xAxisLabels[0], avgKpi],
      [xAxisLabels[xAxisLabels.length - 1], avgKpi],
    ]);
  }
  const { min: yAxisMin, max: yAxisMax } = getYAxisBounds(boundsInput);

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
          // Match the X-axis label interval by keying off the category index
          // (p.name) instead of the series data index. currentSeries can be
          // shorter than xAxisLabels when points are null/skipped, so using
          // dataIndex would desync the value labels from the X-axis ticks.
          const catIdx = xAxisLabels.indexOf(p.name);
          if (catIdx < 0) {
            return '';
          }
          const isLast = catIdx === xAxisLabels.length - 1;
          if (isLast) return fmtRatioTrimTrailingZero(Number(value));
          const show = getXAxisLabelIntervalFn(xAxisLabels.length);
          return show(catIdx) ? fmtRatioTrimTrailingZero(Number(value)) : '';
        },
      },
      // Interval thinning alone cannot prevent collisions: neighbouring labels
      // still touch when the line is steep or the chart is narrow.
      labelLayout: { hideOverlap: true },
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

  if (avgKpi !== null) {
    series.push({
      name: t('KPI'),
      type: 'line',
      data: [],
      z: 1,
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { type: 'solid', width: 1, color: '#2CA02C' },
        label: {
          show: true,
          position: 'insideStartTop',
          color: '#2CA02C',
          fontSize: 15,
          fontWeight: 600,
          formatter: () => fmtRatio(avgKpi),
        },
        data: [{ yAxis: avgKpi }],
      },
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
        interval: getXAxisLabelIntervalFn(xAxisLabels.length),
        margin: 12,
        rotate: 0,
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
      appendToBody: true,
      confine: false,
      extraCssText: 'min-width:180px; white-space:nowrap;',
      formatter: (params: any) => {
        if (!Array.isArray(params)) return '';
        // Header is the FULL x-axis label (untruncated, not space-split)
        let html = `${String(params[0].name)}<br/>`;
        params.forEach((p: any) => {
          const value = p.data[1];
          const val = value !== null ? fmtRatio(Number(value)) : 'N/A';
          if (isThreeMetric) {
            html += `${p.marker} ${p.seriesName}: ${val}<br/>`;
          } else {
            const raw =
              p.data[2] !== undefined && p.data[3] !== undefined
                ? ` (${fmtInt(Number(p.data[2]))} / ${fmtInt(
                  Number(p.data[3]),
                )})`
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
      right: 12,
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
    showCurrentAbsolute: !isThreeMetric,
    prevRatio,
    kpiTarget: avgKpi,
    bigNumberUnit: resolvedBigNumberUnit,
    kpiComparison,
    prevPeriodComparison,
    monthToDateRatio,
    monthToDateComparison,
    currentSeries,
    prevSeries,
    kpiTargetSeries:
      avgKpi !== null
        ? [
          [firstX, avgKpi],
          [lastX, avgKpi],
        ]
        : [],
    echartOptions,
    formData,
    onContextMenu,
    numberFormatter,
  };
}
