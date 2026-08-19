import { t, SupersetClient } from '@superset-ui/core';
import { Menu } from 'src/components/Menu';
import { useToasts } from 'src/components/MessageToasts/withToasts';
import { useCallback } from 'react';
import domToImage from 'dom-to-image-more';

interface ChartImageData {
  image: string;
  name?: string;
  row: number;
  col: number;
  width: number;
  height: number;
  sliceId?: string;
}

interface KpiChartStatus {
  group: 'none' | 'common' | 'key';
  status: 'passed' | 'failed' | 'no_data';
  title?: string;
  sliceId?: string;
}

interface KpiExportCounts {
  kpi_total: number;
  kpi_common_total: number;
  kpi_common_passed: number;
  kpi_common_failed: number;
  kpi_common_no_data: number;
  kpi_common_not_passed: number;
  kpi_common_passed_rate: string;
  kpi_key_total: number;
  kpi_key_passed: number;
  kpi_key_failed: number;
  kpi_key_no_data: number;
  kpi_key_not_passed: number;
  kpi_key_passed_rate: string;
  kpi_total_passed: number;
  kpi_total_not_passed: number;
}

export const CHART_HOLDER_SELECTOR = '.dashboard-component-chart-holder';
const KPI_LINE_CHART_SELECTOR = '[data-kpi-line-chart="true"]';
const DASHBOARD_TAB_BUTTON_SELECTOR =
  '.dashboard-component-tabs .ant-tabs-tab-btn';
const WORD_EXPORT_CAPTURE_CLASS = 'superset-word-export-capturing';
const EXPORT_CHART_HOLDER_STYLE = {
  transform: 'none',
  border: 'none',
  borderRadius: '0',
  boxShadow: 'none',
  padding: '0',
};
const EXPORT_CHART_CHROME_SELECTOR = [
  '.dashboard-component-chart-holder',
  '.dashboard-component-chart',
  '[data-test="chart-grid-component"]',
  '.chart-slice',
].join(',');
const TAB_CAPTURE_RENDER_DELAY = 10000;
const MAX_TAB_CAPTURE_STEPS = 100;

const sleep = (ms: number) =>
  new Promise(resolve => {
    window.setTimeout(resolve, ms);
  });

function isElementVisible(element: HTMLElement): boolean {
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) {
    return false;
  }

  let current: HTMLElement | null = element;
  while (current) {
    const style = window.getComputedStyle(current);
    if (
      style.display === 'none' ||
      style.visibility === 'hidden' ||
      current.getAttribute('aria-hidden') === 'true'
    ) {
      return false;
    }
    current = current.parentElement;
  }

  return true;
}

function getDashboardTabDepth(element: HTMLElement): number {
  let depth = 0;
  let current = element.parentElement;
  while (current) {
    if (current.classList.contains('dashboard-component-tabs')) {
      depth += 1;
    }
    current = current.parentElement;
  }
  return depth;
}

function isActiveTabButton(button: HTMLElement): boolean {
  return Boolean(
    button.closest('.ant-tabs-tab')?.classList.contains('ant-tabs-tab-active'),
  );
}

function getVisibleDashboardTabButtons(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(DASHBOARD_TAB_BUTTON_SELECTOR),
  ).filter(isElementVisible);
}

function getElementDomIndex(element: HTMLElement): number {
  return Array.from(document.querySelectorAll('*')).indexOf(element);
}

function getTabButtonKey(button: HTMLElement): string {
  const tabContainer = button.closest('.dashboard-component-tabs');
  const tabButtons = tabContainer
    ? Array.from(
        tabContainer.querySelectorAll<HTMLElement>('.ant-tabs-tab-btn'),
      )
    : [];
  const tabIndex = tabButtons.indexOf(button);
  return [
    getElementDomIndex(tabContainer as HTMLElement),
    tabIndex,
    button.textContent?.trim() ?? '',
  ].join('|');
}

function removeChartChromeForExport(element: HTMLElement) {
  element.style.setProperty('border', '0', 'important');
  element.style.setProperty('border-radius', '0', 'important');
  element.style.setProperty('box-shadow', 'none', 'important');
  element.style.setProperty('-webkit-box-shadow', 'none', 'important');
  element.style.setProperty('outline', '0', 'important');
  element.style.setProperty('padding', '0', 'important');
}

function removeChartChromeFromClone(clone: HTMLElement) {
  removeChartChromeForExport(clone);
  clone
    .querySelectorAll<HTMLElement>(EXPORT_CHART_CHROME_SELECTOR)
    .forEach(removeChartChromeForExport);
}

async function waitForDashboardRender() {
  window.dispatchEvent(new Event('resize'));
  await sleep(TAB_CAPTURE_RENDER_DELAY);
  window.dispatchEvent(new Event('resize'));
  await sleep(250);
}

async function captureChartImage(
  chartContainer: HTMLElement,
  index: number,
): Promise<ChartImageData | null> {
  const chartMetadataContainer =
    chartContainer.closest('[data-test-chart-name]') ??
    chartContainer.querySelector('[data-test-chart-name]');
  const rect = chartContainer.getBoundingClientRect();

  // Must measure the element being rendered, not a descendant: dom-to-image
  // overwrites the clone's width/height with these values rather than cropping,
  // so a smaller size squashes the chart and clips the X axis off the bottom.
  const contentWidth = Math.ceil(rect.width);
  const contentHeight = Math.ceil(rect.height);

  const gridRow = chartContainer.style.gridRow || 'auto';
  const gridCol = chartContainer.style.gridColumn || 'auto';
  const row = parseInt(gridRow.split('/')[0].trim(), 10) - 1 || index;
  const col = parseInt(gridCol.split('/')[0].trim(), 10) - 1 || 0;
  const chartName =
    chartMetadataContainer?.getAttribute('data-test-chart-name') ??
    chartContainer.getAttribute('data-test-chart-name') ??
    undefined;

  try {
    const dataUrl = await domToImage.toPng(chartContainer, {
      width: contentWidth,
      height: contentHeight,
      style: EXPORT_CHART_HOLDER_STYLE,
      onclone: removeChartChromeFromClone,
    });

    return {
      image: dataUrl,
      name: chartName,
      row,
      col,
      width: Math.round(contentWidth),
      height: Math.round(contentHeight),
      sliceId:
        chartMetadataContainer?.getAttribute('data-test-chart-id') ??
        chartContainer.getAttribute('data-test-chart-id') ??
        undefined,
    };
  } catch {
    return null;
  }
}

function getChartCaptureKey(chart: ChartImageData): string {
  return (
    chart.sliceId ||
    chart.name ||
    `${chart.row}:${chart.col}:${chart.width}:${chart.height}`
  );
}

function getKpiChartStatusKey(element: HTMLElement): string {
  const chartContainer = element.closest('[data-test-chart-id]');
  return [
    chartContainer?.getAttribute('data-test-chart-id') ?? '',
    element.getAttribute('data-kpi-title') ?? '',
    getElementDomIndex(element),
  ].join('|');
}

function getKpiChartStatus(element: HTMLElement): KpiChartStatus {
  const chartContainer = element.closest('[data-test-chart-id]');
  const rawGroup = element.getAttribute('data-kpi-group');
  const group = rawGroup === 'common' || rawGroup === 'key' ? rawGroup : 'none';
  const rawStatus = element.getAttribute('data-kpi-status');
  const status =
    rawStatus === 'passed' || rawStatus === 'failed' || rawStatus === 'no_data'
      ? rawStatus
      : 'no_data';

  return {
    group,
    status,
    title: element.getAttribute('data-kpi-title') ?? undefined,
    sliceId: chartContainer?.getAttribute('data-test-chart-id') ?? undefined,
  };
}

function collectVisibleKpiChartStatuses(
  capturedKpiCharts: Map<string, KpiChartStatus>,
) {
  const kpiChartElements = Array.from(
    document.querySelectorAll<HTMLElement>(KPI_LINE_CHART_SELECTOR),
  ).filter(isElementVisible);

  kpiChartElements.forEach(element => {
    capturedKpiCharts.set(
      getKpiChartStatusKey(element),
      getKpiChartStatus(element),
    );
  });
}

function calculatePassedRate(passed: number, total: number): string {
  if (total <= 0) {
    return '0';
  }
  return ((passed / total) * 100).toFixed(2);
}

function buildKpiExportCounts(
  kpiCharts: Map<string, KpiChartStatus>,
): KpiExportCounts {
  const counts: KpiExportCounts = {
    kpi_total: 0,
    kpi_common_total: 0,
    kpi_common_passed: 0,
    kpi_common_failed: 0,
    kpi_common_no_data: 0,
    kpi_common_not_passed: 0,
    kpi_common_passed_rate: '0',
    kpi_key_total: 0,
    kpi_key_passed: 0,
    kpi_key_failed: 0,
    kpi_key_no_data: 0,
    kpi_key_not_passed: 0,
    kpi_key_passed_rate: '0',
    kpi_total_passed: 0,
    kpi_total_not_passed: 0,
  };

  kpiCharts.forEach(chart => {
    if (chart.group === 'none') {
      return;
    }

    if (chart.group === 'key') {
      counts.kpi_key_total += 1;
      if (chart.status === 'passed') {
        counts.kpi_key_passed += 1;
      } else if (chart.status === 'failed') {
        counts.kpi_key_failed += 1;
      } else {
        counts.kpi_key_no_data += 1;
      }
    } else {
      counts.kpi_common_total += 1;
      if (chart.status === 'passed') {
        counts.kpi_common_passed += 1;
      } else if (chart.status === 'failed') {
        counts.kpi_common_failed += 1;
      } else {
        counts.kpi_common_no_data += 1;
      }
    }
  });

  counts.kpi_common_not_passed =
    counts.kpi_common_total - counts.kpi_common_passed;
  counts.kpi_key_not_passed = counts.kpi_key_total - counts.kpi_key_passed;
  counts.kpi_total = counts.kpi_common_total + counts.kpi_key_total;
  counts.kpi_total_passed = counts.kpi_common_passed + counts.kpi_key_passed;
  counts.kpi_total_not_passed =
    counts.kpi_common_not_passed + counts.kpi_key_not_passed;
  counts.kpi_common_passed_rate = calculatePassedRate(
    counts.kpi_common_passed,
    counts.kpi_common_total,
  );
  counts.kpi_key_passed_rate = calculatePassedRate(
    counts.kpi_key_passed,
    counts.kpi_key_total,
  );

  return counts;
}

async function captureVisibleCharts(
  capturedCharts: Map<string, ChartImageData>,
) {
  const chartContainers = Array.from(
    document.querySelectorAll<HTMLElement>(CHART_HOLDER_SELECTOR),
  ).filter(isElementVisible);

  const chartCaptureResults = await Promise.all(
    chartContainers.map((chartContainer, index) =>
      captureChartImage(chartContainer, index),
    ),
  );

  chartCaptureResults.forEach(chart => {
    if (chart) {
      capturedCharts.set(getChartCaptureKey(chart), chart);
    }
  });
}

async function captureVisibleDashboardState(
  capturedCharts: Map<string, ChartImageData>,
  capturedKpiCharts: Map<string, KpiChartStatus>,
) {
  await captureVisibleCharts(capturedCharts);
  collectVisibleKpiChartStatuses(capturedKpiCharts);
}

async function restoreActiveTabs(originalActiveButtons: HTMLElement[]) {
  const buttonsToRestore = [...originalActiveButtons].sort(
    (first, second) =>
      getDashboardTabDepth(first) - getDashboardTabDepth(second),
  );

  for (const button of buttonsToRestore) {
    if (button.isConnected && !isActiveTabButton(button)) {
      button.click();
      // eslint-disable-next-line no-await-in-loop
      await waitForDashboardRender();
    }
  }
}

async function captureDashboardStateAcrossTabs(): Promise<{
  charts: ChartImageData[];
  kpiCounts: KpiExportCounts;
}> {
  const capturedCharts = new Map<string, ChartImageData>();
  const capturedKpiCharts = new Map<string, KpiChartStatus>();
  const originalScrollX = window.scrollX;
  const originalScrollY = window.scrollY;
  const originalActiveButtons =
    getVisibleDashboardTabButtons().filter(isActiveTabButton);
  const visitedTabKeys = new Set<string>();

  try {
    document.body.classList.add(WORD_EXPORT_CAPTURE_CLASS);
    await waitForDashboardRender();
    await captureVisibleDashboardState(capturedCharts, capturedKpiCharts);

    let step = 0;
    while (step < MAX_TAB_CAPTURE_STEPS) {
      const visibleTabButtons = getVisibleDashboardTabButtons();
      visibleTabButtons.forEach(button => {
        if (isActiveTabButton(button)) {
          visitedTabKeys.add(getTabButtonKey(button));
        }
      });

      const nextButton = visibleTabButtons
        .filter(
          button =>
            !isActiveTabButton(button) &&
            !visitedTabKeys.has(getTabButtonKey(button)),
        )
        .sort((first, second) => {
          const depthDiff =
            getDashboardTabDepth(second) - getDashboardTabDepth(first);
          if (depthDiff !== 0) {
            return depthDiff;
          }
          return getElementDomIndex(first) - getElementDomIndex(second);
        })[0];

      if (!nextButton) {
        break;
      }

      visitedTabKeys.add(getTabButtonKey(nextButton));
      nextButton.click();
      // eslint-disable-next-line no-await-in-loop
      await waitForDashboardRender();
      // eslint-disable-next-line no-await-in-loop
      await captureVisibleDashboardState(capturedCharts, capturedKpiCharts);
      step += 1;
    }
  } finally {
    document.body.classList.remove(WORD_EXPORT_CAPTURE_CLASS);
    await restoreActiveTabs(originalActiveButtons);
    window.scrollTo(originalScrollX, originalScrollY);
  }

  return {
    charts: Array.from(capturedCharts.values()),
    kpiCounts: buildKpiExportCounts(capturedKpiCharts),
  };
}

export async function captureDashboardChartsAcrossTabs(): Promise<
  ChartImageData[]
> {
  return (await captureDashboardStateAcrossTabs()).charts;
}

export async function captureDashboardChartsAndKpiCountsAcrossTabs(): Promise<{
  charts: ChartImageData[];
  kpiCounts: KpiExportCounts;
}> {
  return captureDashboardStateAcrossTabs();
}

export function getFilenameFromContentDisposition(
  value: string | null,
): string | null {
  if (!value) return null;

  const encodedFilename = value.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encodedFilename) {
    try {
      return decodeURIComponent(encodedFilename);
    } catch {
      return encodedFilename;
    }
  }

  return value.match(/filename="?([^";]+)"?/i)?.[1] ?? null;
}

export function formatDateDMY(isoDate: string): string {
  if (!isoDate || !/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    return isoDate;
  }
  const [year, month, day] = isoDate.split('-');
  return `${day}/${month}/${year}`;
}

export default function DownloadWord({
  dashboardId,
  dashboardTitle,
  ...rest
}: {
  dashboardId: string;
  dashboardTitle: string;
}) {
  const { addDangerToast, addSuccessToast, addInfoToast } = useToasts();

  const onDownloadWord = useCallback(async () => {
    try {
      addInfoToast(t('Generating Word document, please wait...'), {
        noDuplicate: true,
      });

      if (!document.querySelector(CHART_HOLDER_SELECTOR)) {
        addDangerToast(t('No charts found on this dashboard.'));
        return;
      }

      const { charts, kpiCounts } =
        await captureDashboardChartsAndKpiCountsAcrossTabs();

      if (charts.length === 0) {
        addDangerToast(t('Could not capture any chart images.'));
        return;
      }

      // eslint-disable-next-line no-console
      console.log('[WordExport] KPI counts:', kpiCounts);

      const urlParams = new URLSearchParams(window.location.search);
      const currentStartDate = urlParams.get('current_start_date') || '';
      const currentEndDate = urlParams.get('current_end_date') || '';
      const timeGrain =
        urlParams.get('time_grain') || urlParams.get('timegrain') || '';

      const response = await SupersetClient.post({
        endpoint: `/api/v1/dashboard/${dashboardId}/export_word/`,
        jsonPayload: {
          charts,
          dashboard_title: dashboardTitle || 'Dashboard',
          // Raw ISO dates: the server owns all label/date formatting
          // (report_context.build_template_context).
          time_grain: timeGrain,
          current_start_date: currentStartDate,
          current_end_date: currentEndDate,
          kpi_counts: kpiCounts,
        },
        parseMethod: 'raw',
        headers: {
          Accept:
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      });

      const blob = await (response as Response).blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      const responseFilename = getFilenameFromContentDisposition(
        (response as Response).headers.get('Content-Disposition'),
      );
      a.href = url;
      a.download =
        responseFilename ||
        `${(dashboardTitle || 'Dashboard').replace(
          /[^a-zA-Z0-9]/g,
          '_',
        )}_export.docx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      addSuccessToast(t('Word document downloaded successfully.'));
    } catch {
      addDangerToast(t('Failed to generate Word document. Please try again.'));
    }
  }, [
    dashboardId,
    dashboardTitle,
    addDangerToast,
    addSuccessToast,
    addInfoToast,
  ]);

  return (
    <Menu.Item key="word" {...rest}>
      <div onClick={onDownloadWord} role="button" tabIndex={0}>
        {t('Download as Word')}
      </div>
    </Menu.Item>
  );
}
