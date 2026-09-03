import {
  useState,
  useCallback,
  useMemo,
  useEffect,
  useRef,
} from 'react';
import { styled } from '@superset-ui/core';
import { DatePicker as AntdDatePicker } from 'antd';
import type { Moment } from 'moment';
import moment from 'moment';
import Select from 'src/components/Select/Select';
import { TimeFilterVizProps } from './types';

const Container = styled.div`
  display: flex;
  flex-direction: column;
  width: 100%;
  height: auto;
  min-height: 0;
  padding: 0 8px 2px;
  gap: 2px;
  font-family: sans-serif;
  box-sizing: border-box;
  overflow-y: auto;
`;

const Label = styled.label`
  display: block;
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  line-height: 14px;
  color: ${({ theme }) => theme.colors.grayscale.dark1};
`;

const StyledDatePicker = styled(AntdDatePicker)`
  width: 100%;
  height: 28px;
  padding: 0 8px;
  border-radius: ${({ theme }) => theme.gridUnit}px;

  .ant-picker-input > input {
    font-size: 12px;
  }
`;

const Row = styled.div`
  display: flex;
  flex-direction: row;
  gap: 8px;
`;

const Col = styled.div`
  display: flex;
  flex-direction: column;
  flex: 1;
`;

const HalfCol = styled.div`
  display: flex;
  flex-direction: column;
  width: 100%;
  flex-shrink: 0;
`;

const GrainCol = styled.div`
  display: flex;
  flex-direction: column;
  width: 50%;
  flex-shrink: 0;
`;

const CustomDateGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 8px;

  @media (max-width: 640px) {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
`;

const GRAIN_OPTIONS: { value: string; label: string }[] = [
  { value: 'day', label: 'Ngày' },
  { value: 'week', label: 'Tuần' },
  { value: 'month', label: 'Tháng' },
  { value: 'quarter', label: 'Quý' },
  { value: 'year', label: 'Năm' },
  { value: 'custom', label: 'Custom' },
];

type TimeGroup = 'day' | 'month';

type DateBounds = {
  startDate: string;
  endDate: string;
};

function formatDate(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(
    2,
    '0',
  )}-${String(date.getDate()).padStart(2, '0')}`;
}

function isValidDateStr(dateStr: string): boolean {
  if (!dateStr) return false;
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(dateStr) && !Number.isNaN(Date.parse(dateStr))
  );
}

function addDays(dateStr: string, days: number): string {
  const d = new Date(`${dateStr}T00:00:00.000Z`);
  if (Number.isNaN(d.getTime())) return '';
  d.setUTCDate(d.getUTCDate() + days);
  return formatDate(d);
}

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

function addMonths(dateStr: string, months: number): string {
  if (!isValidDateStr(dateStr)) return '';

  const [yearStr, monthStr, dayStr] = dateStr.split('-');
  const year = Number(yearStr);
  const month = Number(monthStr);
  const day = Number(dayStr);
  const targetMonthIndex = year * 12 + (month - 1) + months;
  const targetYear = Math.floor(targetMonthIndex / 12);
  const targetMonth = (targetMonthIndex % 12) + 1;
  const targetDay = Math.min(day, daysInMonth(targetYear, targetMonth));

  return `${targetYear}-${String(targetMonth).padStart(2, '0')}-${String(
    targetDay,
  ).padStart(2, '0')}`;
}

function daysBetween(startDate: string, endDate: string): number | null {
  if (!isValidDateStr(startDate) || !isValidDateStr(endDate)) return null;
  const startTime = Date.parse(`${startDate}T00:00:00.000Z`);
  const endTime = Date.parse(`${endDate}T00:00:00.000Z`);
  if (endTime < startTime) return null;
  return Math.floor((endTime - startTime) / 86400000) + 1;
}

function buildTimeRangeFromBounds(bounds: DateBounds | null): string {
  if (!bounds) return '';
  return `${bounds.startDate} : ${addDays(bounds.endDate, 1)}`;
}

function buildPackedTimeRange(
  currentBounds: DateBounds | null,
  comparisonBounds: DateBounds | null,
  timeGroup: TimeGroup,
): string {
  if (!currentBounds || !comparisonBounds) return '';
  return [
    currentBounds.startDate,
    currentBounds.endDate,
    comparisonBounds.startDate,
    comparisonBounds.endDate,
    timeGroup,
  ].join('|');
}

function buildMonthBounds(year: number, month: number): DateBounds | null {
  if (Number.isNaN(year) || Number.isNaN(month) || month < 1 || month > 12) {
    return null;
  }

  const startDate = `${year}-${String(month).padStart(2, '0')}-01`;
  const endDate = `${year}-${String(month).padStart(2, '0')}-${String(
    daysInMonth(year, month),
  ).padStart(2, '0')}`;

  return { startDate, endDate };
}

function buildQuarterBounds(
  quarterStr: string,
  year: number,
): DateBounds | null {
  const quarterStartMonths: Record<string, number> = {
    Q1: 1,
    Q2: 4,
    Q3: 7,
    Q4: 10,
  };
  const startMonth = quarterStartMonths[quarterStr];
  if (!startMonth || Number.isNaN(year)) return null;

  const startDate = `${year}-${String(startMonth).padStart(2, '0')}-01`;
  return {
    startDate,
    endDate: addDays(addMonths(startDate, 3), -1),
  };
}

function computeDateBounds(
  grain: string,
  params: Record<string, string>,
): DateBounds | null {
  switch (grain) {
    case 'day': {
      if (!isValidDateStr(params.date)) return null;
      return {
        startDate: `${params.date.slice(0, 7)}-01`,
        endDate: params.date,
      };
    }
    case 'month': {
      const month = parseInt(params.month, 10);
      const year = parseInt(params.year, 10);
      return buildMonthBounds(year, month);
    }
    case 'quarter': {
      const year = parseInt(params.year, 10);
      return buildQuarterBounds(params.quarter, year);
    }
    case 'year': {
      const year = parseInt(params.year, 10);
      if (Number.isNaN(year)) return null;
      return { startDate: `${year}-01-01`, endDate: `${year}-12-31` };
    }
    case 'custom': {
      if (
        !isValidDateStr(params.startDate) ||
        !isValidDateStr(params.endDate) ||
        daysBetween(params.startDate, params.endDate) === null
      ) {
        return null;
      }
      return { startDate: params.startDate, endDate: params.endDate };
    }
    case 'week': {
      if (!isValidDateStr(params.weekStart)) return null;
      return {
        startDate: params.weekStart,
        endDate: addDays(params.weekStart, 6),
      };
    }
    default:
      return null;
  }
}

function computeComparisonDateBounds(
  grain: string,
  params: Record<string, string>,
): DateBounds | null {
  switch (grain) {
    case 'day': {
      if (!isValidDateStr(params.date)) return null;
      const comparisonEndDate = addMonths(params.date, -1);
      return {
        startDate: `${comparisonEndDate.slice(0, 7)}-01`,
        endDate: comparisonEndDate,
      };
    }
    case 'month': {
      const month = parseInt(params.month, 10);
      const year = parseInt(params.year, 10);
      const previousMonth = addMonths(
        `${year}-${String(month).padStart(2, '0')}-01`,
        -1,
      );
      return buildMonthBounds(
        Number(previousMonth.slice(0, 4)),
        Number(previousMonth.slice(5, 7)),
      );
    }
    case 'quarter': {
      const currentBounds = computeDateBounds(grain, params);
      if (!currentBounds) return null;
      return {
        startDate: addMonths(currentBounds.startDate, -3),
        endDate: addDays(currentBounds.startDate, -1),
      };
    }
    case 'year': {
      const year = parseInt(params.year, 10);
      if (Number.isNaN(year)) return null;
      return {
        startDate: `${year - 1}-01-01`,
        endDate: `${year - 1}-12-31`,
      };
    }
    case 'custom':
      if (
        !isValidDateStr(params.compareStartDate) ||
        !isValidDateStr(params.compareEndDate) ||
        daysBetween(params.compareStartDate, params.compareEndDate) === null
      ) {
        return null;
      }
      return {
        startDate: params.compareStartDate,
        endDate: params.compareEndDate,
      };
    case 'week': {
      if (!isValidDateStr(params.weekStart)) return null;
      const prevWeekStart = addDays(params.weekStart, -7);
      return {
        startDate: prevWeekStart,
        endDate: addDays(prevWeekStart, 6),
      };
    }
    default:
      return null;
  }
}

function computeTimeGroup(grain: string, bounds: DateBounds | null): TimeGroup {
  if (grain === 'quarter' || grain === 'year') return 'month';
  if (grain === 'custom' && bounds) {
    const dayCount = daysBetween(bounds.startDate, bounds.endDate);
    return dayCount !== null && dayCount > 60 ? 'month' : 'day';
  }
  return 'day';
}

function computeGrainValue(
  grain: string,
  params: Record<string, string>,
): string {
  switch (grain) {
    case 'day':
      return params.date || '';
    case 'month':
      return `${params.year}-${params.month}`;
    case 'quarter':
      return `${params.year}-${params.quarter}`;
    case 'year':
      return params.year || '';
    case 'week':
      return params.weekStart || '';
    case 'custom':
      return `${params.startDate || ''} : ${params.endDate || ''}`;
    default:
      return '';
  }
}

function updateUrlParamsAndReload({
  grain,
  grainValue,
  packedTimeRange,
  currentTimeRange,
  comparisonTimeRange,
  bounds,
  comparisonBounds,
  timeGroup,
}: {
  grain: string;
  grainValue: string;
  packedTimeRange: string;
  currentTimeRange: string;
  comparisonTimeRange: string;
  bounds: DateBounds;
  comparisonBounds: DateBounds;
  timeGroup: TimeGroup;
}) {
  const url = new URL(window.location.href);
  url.searchParams.set('time_grain', grain);
  url.searchParams.set('grain_value', grainValue);
  url.searchParams.set('time_range', packedTimeRange);
  url.searchParams.set('current_time_range', currentTimeRange);
  url.searchParams.set('comparison_time_range', comparisonTimeRange);
  url.searchParams.set('current_start_date', bounds.startDate);
  url.searchParams.set('current_end_date', bounds.endDate);
  url.searchParams.set('comparison_start_date', comparisonBounds.startDate);
  url.searchParams.set('comparison_end_date', comparisonBounds.endDate);
  url.searchParams.set('time_group', timeGroup);

  window.location.assign(url.toString());
}

function getUrlParam(params: URLSearchParams, name: string): string {
  return params.get(name) || '';
}

function hasCompleteTimeFilterParams(params: URLSearchParams): boolean {
  return [
    'time_grain',
    'grain_value',
    'time_range',
    'current_time_range',
    'comparison_time_range',
    'current_start_date',
    'current_end_date',
    'comparison_start_date',
    'comparison_end_date',
    'time_group',
  ].every(name => Boolean(getUrlParam(params, name)));
}

function isValidGrain(grain: string): boolean {
  return GRAIN_OPTIONS.some(option => option.value === grain);
}

function resolveInitialParamsFromUrl(
  urlParams: URLSearchParams,
): { grain: string; params: Record<string, string> } | null {
  const urlGrain = getUrlParam(urlParams, 'time_grain');
  const grain = isValidGrain(urlGrain) ? urlGrain : '';
  const grainValue = getUrlParam(urlParams, 'grain_value');

  if (!grain) return null;

  switch (grain) {
    case 'day': {
      const date = isValidDateStr(grainValue)
        ? grainValue
        : getUrlParam(urlParams, 'current_end_date');
      return isValidDateStr(date) ? { grain, params: { date } } : null;
    }
    case 'month': {
      const match = grainValue.match(/^(\d{4})-(\d{2})$/);
      const startDate = getUrlParam(urlParams, 'current_start_date');
      const year = match?.[1] || startDate.slice(0, 4);
      const month = match?.[2] || startDate.slice(5, 7);
      return buildMonthBounds(Number(year), Number(month))
        ? { grain, params: { year, month } }
        : null;
    }
    case 'quarter': {
      const match = grainValue.match(/^(\d{4})-(Q[1-4])$/);
      const year =
        match?.[1] || getUrlParam(urlParams, 'current_start_date').slice(0, 4);
      const quarter = match?.[2] || '';
      return buildQuarterBounds(quarter, Number(year))
        ? { grain, params: { year, quarter } }
        : null;
    }
    case 'year': {
      const year = /^\d{4}$/.test(grainValue)
        ? grainValue
        : getUrlParam(urlParams, 'current_start_date').slice(0, 4);
      return /^\d{4}$/.test(year) ? { grain, params: { year } } : null;
    }
    case 'week': {
      const weekStart = isValidDateStr(grainValue)
        ? grainValue
        : getUrlParam(urlParams, 'current_start_date');
      return isValidDateStr(weekStart)
        ? { grain, params: { weekStart } }
        : null;
    }
    case 'custom': {
      const startDate = getUrlParam(urlParams, 'current_start_date');
      const endDate = getUrlParam(urlParams, 'current_end_date');
      const compareStartDate = getUrlParam(urlParams, 'comparison_start_date');
      const compareEndDate = getUrlParam(urlParams, 'comparison_end_date');
      const params = {
        startDate,
        endDate,
        compareStartDate,
        compareEndDate,
      };
      return computeDateBounds(grain, params) &&
        computeComparisonDateBounds(grain, params)
        ? { grain, params }
        : null;
    }
    default:
      return null;
  }
}

function applySelectionToUrlAndReload(
  grain: string,
  params: Record<string, string>,
) {
  const bounds = computeDateBounds(grain, params);
  const comparisonBounds = computeComparisonDateBounds(grain, params);
  if (!bounds || !comparisonBounds) return;

  const timeGroup = computeTimeGroup(grain, bounds);
  const grainValue = computeGrainValue(grain, params);
  updateUrlParamsAndReload({
    grain,
    grainValue,
    packedTimeRange: buildPackedTimeRange(bounds, comparisonBounds, timeGroup),
    currentTimeRange: buildTimeRangeFromBounds(bounds),
    comparisonTimeRange: buildTimeRangeFromBounds(comparisonBounds),
    bounds,
    comparisonBounds,
    timeGroup,
  });
}

export default function TimeFilterChart(props: TimeFilterVizProps) {
  const { setDataMask } = props;
  const shouldReloadRef = useRef(false);
  const initializedRef = useRef(false);

  const maxDate = useMemo(() => new Date(), []);

  const maxYear = maxDate.getFullYear();
  const maxMonth = String(maxDate.getMonth() + 1).padStart(2, '0');
  const maxQtr = `Q${Math.ceil((maxDate.getMonth() + 1) / 3)}`;

  const [grain, setGrain] = useState('day');
  const [dayValue, setDayValue] = useState(formatDate(maxDate));
  const [weekStartDate, setWeekStartDate] = useState('');
  const [weekEndDate, setWeekEndDate] = useState('');
  const [monthValue, setMonthValue] = useState(maxMonth);
  const [monthYear, setMonthYear] = useState(String(maxYear));
  const [quarterValue, setQuarterValue] = useState(maxQtr);
  const [quarterYear, setQuarterYear] = useState(String(maxYear));
  const [yearValue, setYearValue] = useState(String(maxYear));
  const [customStartDate, setCustomStartDate] = useState('');
  const [customEndDate, setCustomEndDate] = useState('');
  const [compareStartDate, setCompareStartDate] = useState('');
  const [compareEndDate, setCompareEndDate] = useState('');
  const [isReady, setIsReady] = useState(false);
  const [customCommitVersion, setCustomCommitVersion] = useState(0);

  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;

    const urlParams = new URL(window.location.href).searchParams;
    const initialSelection = resolveInitialParamsFromUrl(urlParams);

    if (!initialSelection) {
      applySelectionToUrlAndReload('day', { date: formatDate(maxDate) });
      return;
    }

    const { grain: initialGrain, params } = initialSelection;
    if (!hasCompleteTimeFilterParams(urlParams)) {
      applySelectionToUrlAndReload(initialGrain, params);
      return;
    }

    setGrain(initialGrain);
    switch (initialGrain) {
      case 'day':
        setDayValue(params.date);
        break;
      case 'month':
        setMonthValue(params.month);
        setMonthYear(params.year);
        break;
      case 'quarter':
        setQuarterValue(params.quarter);
        setQuarterYear(params.year);
        break;
      case 'year':
        setYearValue(params.year);
        break;
      case 'week':
        setWeekStartDate(params.weekStart);
        setWeekEndDate(addDays(params.weekStart, 6));
        break;
      case 'custom':
        setCustomStartDate(params.startDate);
        setCustomEndDate(params.endDate);
        setCompareStartDate(params.compareStartDate);
        setCompareEndDate(params.compareEndDate);
        break;
      default:
        break;
    }
    setIsReady(true);
  }, [maxDate]);

  const getParams = useCallback((): Record<string, string> => {
    switch (grain) {
      case 'day':
        return { date: dayValue };
      case 'month':
        return { month: monthValue, year: monthYear };
      case 'quarter':
        return { quarter: quarterValue, year: quarterYear };
      case 'year':
        return { year: yearValue };
      case 'week':
        return { weekStart: weekStartDate };
      case 'custom':
        return {
          startDate: customStartDate,
          endDate: customEndDate,
          compareStartDate,
          compareEndDate,
        };
      default:
        return {};
    }
  }, [
    grain,
    dayValue,
    weekStartDate,
    monthValue,
    monthYear,
    quarterValue,
    quarterYear,
    yearValue,
    customStartDate,
    customEndDate,
    compareStartDate,
    compareEndDate,
  ]);

  const emitFilter = useCallback(
    (g: string, params: Record<string, string>) => {
      if (!setDataMask) return;

      const bounds = computeDateBounds(g, params);
      const comparisonBounds = computeComparisonDateBounds(g, params);
      const grainValue = computeGrainValue(g, params);
      const timeGroup = computeTimeGroup(g, bounds);
      const timeRange = buildTimeRangeFromBounds(bounds);
      const comparisonTimeRange = buildTimeRangeFromBounds(comparisonBounds);
      const packedTimeRange = buildPackedTimeRange(
        bounds,
        comparisonBounds,
        timeGroup,
      );

      if (!timeRange || !packedTimeRange) return;
      if (g === 'custom' && !comparisonTimeRange) return;

      console.log('[TimeFilter] selected values:', {
        grain: g,
        grainValue,
        timeGroup,
        currentStartDate: bounds?.startDate,
        currentEndDate: bounds?.endDate,
        comparisonStartDate: comparisonBounds?.startDate,
        comparisonEndDate: comparisonBounds?.endDate,
        timeRange: packedTimeRange,
        currentTimeRange: timeRange,
        comparisonTimeRange,
      });

      setDataMask({
        extraFormData: {
          time_range: packedTimeRange,
          current_time_range: timeRange,
          comparison_time_range: comparisonTimeRange,
          current_start_date: bounds?.startDate,
          current_end_date: bounds?.endDate,
          comparison_start_date: comparisonBounds?.startDate,
          comparison_end_date: comparisonBounds?.endDate,
          time_group: timeGroup,
        },
        filterState: {
          value: grainValue,
          filters: {
            time_range: packedTimeRange,
            current_time_range: timeRange,
            time_group: timeGroup,
            comparison_time_range: comparisonTimeRange,
            current_start_date: bounds?.startDate,
            current_end_date: bounds?.endDate,
            comparison_start_date: comparisonBounds?.startDate,
            comparison_end_date: comparisonBounds?.endDate,
            grain: g,
            grainValue,
          },
        },
      });

      if (shouldReloadRef.current && bounds && comparisonBounds) {
        shouldReloadRef.current = false;
        updateUrlParamsAndReload({
          grain: g,
          grainValue,
          packedTimeRange,
          currentTimeRange: timeRange,
          comparisonTimeRange,
          bounds,
          comparisonBounds,
          timeGroup,
        });
      }
    },
    [setDataMask],
  );

  useEffect(() => {
    if (!isReady) return;

    const params = getParams();
    emitFilter(grain, params);
  }, [
    isReady,
    grain,
    dayValue,
    weekStartDate,
    monthValue,
    monthYear,
    quarterValue,
    quarterYear,
    yearValue,
    customStartDate,
    customEndDate,
    compareStartDate,
    compareEndDate,
    customCommitVersion,
    emitFilter,
    getParams,
  ]);

  const handleGrainChange = (value: string) => {
    shouldReloadRef.current = value !== 'custom';
    setGrain(value);
  };

  const handleValueChange = useCallback((change: () => void) => {
    shouldReloadRef.current = true;
    change();
  }, []);

  const handleCustomDateCommit = useCallback(() => {
    const params = {
      startDate: customStartDate,
      endDate: customEndDate,
      compareStartDate,
      compareEndDate,
    };

    if (
      !computeDateBounds('custom', params) ||
      !computeComparisonDateBounds('custom', params)
    ) {
      shouldReloadRef.current = false;
      return;
    }

    shouldReloadRef.current = true;
    setCustomCommitVersion(version => version + 1);
  }, [customStartDate, customEndDate, compareStartDate, compareEndDate]);

  const renderDayPicker = () => (
    <Col>
      <Label>Day</Label>
      <StyledDatePicker
        value={dayValue ? moment(dayValue) : null}
        onChange={(date: Moment | null) =>
          handleValueChange(() => setDayValue(date ? date.format('YYYY-MM-DD') : ''))
        }
      />
    </Col>
  );

  const renderWeekPicker = () => (
    <Row>
      <Col>
        <Label>Start date</Label>
        <StyledDatePicker
          value={weekStartDate ? moment(weekStartDate) : null}
          onChange={(date: Moment | null) => {
            const start = date ? date.format('YYYY-MM-DD') : '';
            handleValueChange(() => {
              setWeekStartDate(start);
              setWeekEndDate(start ? addDays(start, 6) : '');
            });
          }}
        />
      </Col>
      <Col>
        <Label>End date</Label>
        <StyledDatePicker
          value={weekEndDate ? moment(weekEndDate) : null}
          onChange={(date: Moment | null) =>
            handleValueChange(() => setWeekEndDate(date ? date.format('YYYY-MM-DD') : ''))
          }
        />
      </Col>
    </Row>
  );

  const renderYearPicker = () => (
    <Col>
      <Label>Year</Label>
      <StyledDatePicker
        picker="year"
        value={yearValue ? moment(yearValue, 'YYYY') : null}
        onChange={(date: Moment | null) =>
          handleValueChange(() => setYearValue(date ? date.format('YYYY') : ''))
        }
      />
    </Col>
  );

  const renderMonthPicker = () => (
    <Col>
      <Label>Month</Label>
      <StyledDatePicker
        picker="month"
        value={monthYear && monthValue ? moment(`${monthYear}-${monthValue}`, 'YYYY-MM') : null}
        onChange={(date: Moment | null) => {
          handleValueChange(() => {
            setMonthValue(date ? date.format('MM') : '');
            setMonthYear(date ? date.format('YYYY') : '');
          });
        }}
      />
    </Col>
  );

  const renderQuarterPicker = () => (
    <Col>
      <Label>Quarter</Label>
      <StyledDatePicker
        picker="quarter"
        value={quarterYear && quarterValue
          ? moment(`${quarterYear}-${quarterValue}`, 'YYYY-[Q]Q')
          : null}
        onChange={(date: Moment | null) => {
          handleValueChange(() => {
            setQuarterValue(date ? `Q${date.quarter()}` : '');
            setQuarterYear(date ? date.format('YYYY') : '');
          });
        }}
      />
    </Col>
  );

  const renderCustomPicker = () => (
    <CustomDateGrid>
      <HalfCol>
        <Label>Start date</Label>
        <StyledDatePicker
          value={customStartDate ? moment(customStartDate) : null}
          onChange={(date: Moment | null) => setCustomStartDate(date ? date.format('YYYY-MM-DD') : '')}
          onBlur={handleCustomDateCommit}
        />
      </HalfCol>
      <HalfCol>
        <Label>End date</Label>
        <StyledDatePicker
          value={customEndDate ? moment(customEndDate) : null}
          onChange={(date: Moment | null) => setCustomEndDate(date ? date.format('YYYY-MM-DD') : '')}
          onBlur={handleCustomDateCommit}
        />
      </HalfCol>
      <HalfCol>
        <Label>Compare start</Label>
        <StyledDatePicker
          value={compareStartDate ? moment(compareStartDate) : null}
          onChange={(date: Moment | null) => setCompareStartDate(date ? date.format('YYYY-MM-DD') : '')}
          onBlur={handleCustomDateCommit}
        />
      </HalfCol>
      <HalfCol>
        <Label>Compare end</Label>
        <StyledDatePicker
          value={compareEndDate ? moment(compareEndDate) : null}
          onChange={(date: Moment | null) => setCompareEndDate(date ? date.format('YYYY-MM-DD') : '')}
          onBlur={handleCustomDateCommit}
        />
      </HalfCol>
    </CustomDateGrid>
  );

  const renderValuePicker = () => {
    switch (grain) {
      case 'day':
        return renderDayPicker();
      case 'week':
        return renderWeekPicker();
      case 'month':
        return renderMonthPicker();
      case 'quarter':
        return renderQuarterPicker();
      case 'year':
        return renderYearPicker();
      case 'custom':
        return renderCustomPicker();
      default:
        return null;
    }
  };

  return (
    <Container>
      <Row>
        <GrainCol>
          <Label>Time Grain</Label>
          <Select
            ariaLabel="Time Grain"
            options={GRAIN_OPTIONS}
            value={grain}
            onChange={handleGrainChange}
            getPopupContainer={() => document.body}
          />
        </GrainCol>
        {grain !== 'custom' && grain !== 'week' && renderValuePicker()}
      </Row>
      {(grain === 'custom' || grain === 'week') && renderValuePicker()}
    </Container>
  );
}
