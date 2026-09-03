import {
  type KeyboardEvent,
  type MouseEvent,
  useRef,
  useEffect,
  useCallback,
} from 'react';
import { styled } from '@superset-ui/core';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  ToolboxComponent,
  MarkLineComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { KpiLineVizProps } from './types';

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  ToolboxComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

const KPI_HEIGHT_RATIO = 0.38;
const CHART_TOP_GAP = 16;

const Container = styled.div`
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  font-family: ${({ theme }) => theme.typography.families.sansSerif};
  box-sizing: border-box;
  overflow: hidden;
`;

const KpiCard = styled.div`
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  text-align: center;
  padding: 8px 16px;
  flex-shrink: 0;
`;

const BigNumberRow = styled.div`
  display: flex;
  flex-direction: row;
  justify-content: center;
  align-items: baseline;
  gap: 6px;
`;

const BigNumber = styled.div<{ color?: string }>`
  font-size: 27px;
  font-weight: 700;
  color: ${({ color, theme }) => color || theme.colors.grayscale.dark1};
  line-height: 1.2;
`;

const AbsoluteNumber = styled.div`
  font-size: 25px;
  color: ${({ theme }) => theme.colors.grayscale.dark1};
  font-style: italic;
  white-space: nowrap;
`;

const ComparisonLine = styled.div`
  font-size: 25px;
  color: ${({ theme }) => theme.colors.grayscale.dark1};
  line-height: 1.2;

  body.superset-word-export-capturing & {
    font-size: 25px;
    line-height: 1.2;
    white-space: nowrap;
  }
`;

const ComparisonBlock = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
`;

const Spacer = styled.div`
  height: 8px;
  flex-shrink: 0;
`;

const EChartsContainer = styled.div`
  flex: 1;
  min-height: 0;
`;

const GOOD_COLOR = '#2CA02C';
const BAD_COLOR = '#D62728';
const NEUTRAL_COLOR = '#1978D4';

function getTimeGrain(): string {
  if (typeof window === 'undefined') return '';
  return new URLSearchParams(window.location.search).get('time_grain') || '';
}

function getPreviousPeriodLabel(): string {
  const timeGrain = getTimeGrain();
  return timeGrain === 'day' || timeGrain === 'month' || timeGrain === 'custom'
    ? 'cùng kỳ tháng trước'
    : 'kỳ trước';
}

// Month-to-date only makes sense on week-like reports (WEEK_LIKE_GRAINS in report_context.py)
function isWeekLikeGrain(): boolean {
  const timeGrain = getTimeGrain();
  return timeGrain === 'week' || timeGrain === 'custom';
}

function openDetailUrlWithCurrentFilters(detailUrl: string): boolean {
  if (typeof window === 'undefined') {
    return false;
  }

  const trimmedDetailUrl = detailUrl.trim();
  if (!trimmedDetailUrl) {
    return false;
  }

  const targetUrl = new URL(trimmedDetailUrl, window.location.origin);
  const currentParams = new URLSearchParams(window.location.search);
  currentParams.forEach((value, key) => {
    if (!targetUrl.searchParams.has(key)) {
      targetUrl.searchParams.set(key, value);
    }
  });

  const nextUrl =
    targetUrl.origin === window.location.origin
      ? `${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}`
      : targetUrl.toString();
  window.open(nextUrl, '_self');
  return true;
}

export default function KpiLineChart(props: KpiLineVizProps) {
  const {
    width,
    height,
    kpiTitle,
    detailUrl,
    kpiGroup,
    currentRatio,
    currentAbsolute,
    showCurrentAbsolute,
    prevRatio,
    kpiTarget,
    bigNumberUnit,
    kpiComparison,
    prevPeriodComparison,
    monthToDateRatio,
    monthToDateComparison,
    echartOptions,
    onContextMenu,
  } = props;

  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.EChartsType | null>(null);

  const kpiCardHeight = Math.floor(height * KPI_HEIGHT_RATIO);
  const chartHeight = height - kpiCardHeight;
  const chartDisplayHeight = Math.max(0, chartHeight - CHART_TOP_GAP);
  const previousPeriodLabel = getPreviousPeriodLabel();
  const showMonthToDate = isWeekLikeGrain() && monthToDateRatio !== null;
  const allComparisonsNoData =
    kpiComparison.noData &&
    prevPeriodComparison.noData &&
    (!showMonthToDate || monthToDateComparison.noData);
  const hasDetailUrl = detailUrl.trim().length > 0;
  const kpiStatus = kpiComparison.noData
    ? 'no_data'
    : kpiComparison.isGood
      ? 'passed'
      : 'failed';
  const formatKpiValue = (value: number | null) =>
    value !== null
      ? `${value.toLocaleString('vi-VN', {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}${bigNumberUnit}`
      : 'N/A';

  useEffect(() => {
    if (!chartRef.current) return;

    if (!instanceRef.current) {
      instanceRef.current = echarts.init(chartRef.current);
    }

    instanceRef.current.setOption(echartOptions, true);
  }, [echartOptions]);

  useEffect(() => {
    const handleResize = () => {
      instanceRef.current?.resize();
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      instanceRef.current?.dispose();
    };
  }, []);

  useEffect(() => {
    instanceRef.current?.resize({
      width: Math.floor(width),
      height: chartDisplayHeight,
    });
  }, [width, chartDisplayHeight]);

  const renderComparisonText = (
    comparison: {
      direction: string;
      value: number;
      noData?: boolean;
      isGood?: boolean;
    },
    targetLabel: string,
    targetValue: number | null,
    prefix?: string,
  ) => {
    const formattedTargetValue =
      targetValue !== null ? (
        <span>
          {' '}
          (<strong>{formatKpiValue(targetValue)}</strong>)
        </span>
      ) : null;

    if (comparison.noData) {
      return (
        <ComparisonLine>
          {prefix}Không có dữ liệu so với {targetLabel}
        </ComparisonLine>
      );
    }
    const iconColor =
      comparison.isGood === undefined
        ? comparison.direction === 'up'
          ? GOOD_COLOR
          : comparison.direction === 'down'
            ? BAD_COLOR
            : NEUTRAL_COLOR
        : comparison.isGood
          ? GOOD_COLOR
          : BAD_COLOR;
    const directionIcon = comparison.isGood ? '▲' : '▼';
    if (comparison.direction === 'none') {
      return (
        <ComparisonLine>
          {prefix}Không đổi so với {targetLabel}
          {formattedTargetValue}
        </ComparisonLine>
      );
    }
    return (
      <ComparisonLine>
        {prefix}
        <span style={{ color: iconColor, marginRight: 4 }}>
          {directionIcon}
        </span>
        {formatKpiValue(comparison.value)} so với {targetLabel}
        {formattedTargetValue}
      </ComparisonLine>
    );
  };

  const handleContextMenu = useCallback(
    (e: MouseEvent) => {
      if (onContextMenu) {
        e.preventDefault();
        onContextMenu(e.clientX, e.clientY);
      }
    },
    [onContextMenu],
  );

  const handleBigNumberClick = useCallback(
    (e: MouseEvent) => {
      if (!hasDetailUrl) {
        return;
      }
      e.stopPropagation();
      openDetailUrlWithCurrentFilters(detailUrl);
    },
    [hasDetailUrl, detailUrl],
  );

  const handleBigNumberKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!hasDetailUrl) {
        return;
      }
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openDetailUrlWithCurrentFilters(detailUrl);
      }
    },
    [hasDetailUrl, detailUrl],
  );

  return (
    <Container
      data-kpi-line-chart="true"
      data-kpi-title={kpiTitle}
      data-kpi-group={kpiGroup}
      data-kpi-status={kpiStatus}
    >
      <KpiCard
        style={{ height: kpiCardHeight }}
        onContextMenu={handleContextMenu}
      >
        <BigNumberRow>
          <BigNumber
            onClick={handleBigNumberClick}
            onKeyDown={handleBigNumberKeyDown}
            role={hasDetailUrl ? 'button' : undefined}
            tabIndex={hasDetailUrl ? 0 : undefined}
            style={{ cursor: hasDetailUrl ? 'pointer' : 'default' }}
            color={
              kpiComparison.noData
                ? undefined
                : kpiComparison.isGood
                  ? GOOD_COLOR
                  : BAD_COLOR
            }
          >
            {formatKpiValue(currentRatio)}
          </BigNumber>
        </BigNumberRow>
        {showCurrentAbsolute && (
          <AbsoluteNumber>({currentAbsolute})</AbsoluteNumber>
        )}
        <Spacer />
        <ComparisonBlock>
          {allComparisonsNoData ? (
            <ComparisonLine>Không có dữ liệu</ComparisonLine>
          ) : (
            <>
              {renderComparisonText(kpiComparison, 'KPI', kpiTarget)}
              {renderComparisonText(
                prevPeriodComparison,
                previousPeriodLabel,
                prevRatio,
              )}
              {showMonthToDate &&
                renderComparisonText(
                  monthToDateComparison,
                  'KPI',
                  null,
                  `Luỹ kế tháng ${formatKpiValue(monthToDateRatio)} `,
                )}
            </>
          )}
        </ComparisonBlock>
      </KpiCard>
      <EChartsContainer
        ref={chartRef}
        style={{
          width: Math.floor(width),
          height: chartDisplayHeight,
          marginTop: CHART_TOP_GAP,
        }}
      />
    </Container>
  );
}
