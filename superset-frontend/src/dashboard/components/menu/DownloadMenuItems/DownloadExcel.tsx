import { t, SupersetClient } from '@superset-ui/core';
import { Menu } from 'src/components/Menu';
import { useToasts } from 'src/components/MessageToasts/withToasts';
import { useCallback } from 'react';
import {
  CHART_HOLDER_SELECTOR,
  captureDashboardChartsAcrossTabs,
  formatDateDMY,
  getFilenameFromContentDisposition,
} from './DownloadWord';

export default function DownloadExcel({
  dashboardId,
  dashboardTitle,
  ...rest
}: {
  dashboardId: string;
  dashboardTitle: string;
}) {
  const { addDangerToast, addSuccessToast, addInfoToast } = useToasts();

  const onDownloadExcel = useCallback(async () => {
    try {
      addInfoToast(t('Generating Excel workbook, please wait...'), {
        noDuplicate: true,
      });

      if (!document.querySelector(CHART_HOLDER_SELECTOR)) {
        addDangerToast(t('No charts found on this dashboard.'));
        return;
      }

      const charts = await captureDashboardChartsAcrossTabs();

      if (charts.length === 0) {
        addDangerToast(t('Could not capture any chart images.'));
        return;
      }

      const urlParams = new URLSearchParams(window.location.search);
      const currentStartDate = urlParams.get('current_start_date') || '';
      const currentEndDate = urlParams.get('current_end_date') || '';

      const response = await SupersetClient.post({
        endpoint: `/api/v1/dashboard/${dashboardId}/export_excel/`,
        jsonPayload: {
          charts,
          dashboard_title: dashboardTitle || 'Dashboard',
          start_date: formatDateDMY(currentStartDate),
          end_date: formatDateDMY(currentEndDate),
          current_start_date: formatDateDMY(currentStartDate),
          current_end_date: formatDateDMY(currentEndDate),
        },
        parseMethod: 'raw',
        headers: {
          Accept:
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
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
        )}_export.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      addSuccessToast(t('Excel workbook downloaded successfully.'));
    } catch {
      addDangerToast(t('Failed to generate Excel workbook. Please try again.'));
    }
  }, [
    dashboardId,
    dashboardTitle,
    addDangerToast,
    addSuccessToast,
    addInfoToast,
  ]);

  return (
    <Menu.Item key="excel" {...rest}>
      <div onClick={onDownloadExcel} role="button" tabIndex={0}>
        {t('Download as Excel')}
      </div>
    </Menu.Item>
  );
}
