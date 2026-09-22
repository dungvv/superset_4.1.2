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
import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import moment, { Moment } from 'moment';
import { styled, t, SupersetClient } from '@superset-ui/core';
import Modal from 'src/components/Modal';
import { DatePicker } from 'src/components/DatePicker';
import { AlertObject } from '../types';

const SEND_NOW_MAX_BATCH = 10;

export type SendNowItemPayload = {
  id: number;
  name: string;
  filter_date: string;
};

export type SendNowPayload = {
  as_of_date: string;
  items: SendNowItemPayload[];
};

interface SendNowModalProps {
  show: boolean;
  reports: AlertObject[];
  onHide: () => void;
  onSend: (payload: SendNowPayload) => void;
}

const StyledForm = styled.div`
  ${({ theme }) => `
    .required {
      margin-left: ${theme.gridUnit / 2}px;
      color: ${theme.colors.error.base};
    }

    .date-row {
      margin-bottom: ${theme.gridUnit * 4}px;

      .control-label {
        font-weight: ${theme.typography.weights.bold};
        margin-bottom: ${theme.gridUnit}px;
      }
    }

    .reports-table {
      width: 100%;
      border: 1px solid ${theme.colors.grayscale.light2};
      border-radius: ${theme.gridUnit}px;
      overflow: hidden;
    }

    .reports-header,
    .report-row {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(0, 1.3fr) minmax(180px, 1fr);
      column-gap: ${theme.gridUnit * 3}px;
      align-items: center;
      padding: ${theme.gridUnit * 2}px ${theme.gridUnit * 3}px;
      min-height: ${theme.gridUnit * 10}px;
    }

    .reports-header {
      background: ${theme.colors.grayscale.light4};
      border-bottom: 1px solid ${theme.colors.grayscale.light2};
      font-size: ${theme.typography.sizes.s}px;
      font-weight: ${theme.typography.weights.bold};
      color: ${theme.colors.grayscale.base};
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }

    .reports-body {
      max-height: ${theme.gridUnit * 80}px;
      overflow-y: auto;
    }

    .report-row + .report-row {
      border-top: 1px solid ${theme.colors.grayscale.light2};
    }

    .cell {
      min-width: 0;
      display: flex;
      align-items: center;
      line-height: 1.3;
    }

    .report-name {
      font-weight: ${theme.typography.weights.bold};
      word-break: break-word;
    }

    .dataset-name {
      color: ${theme.colors.grayscale.dark1};
      word-break: break-word;
    }

    .dataset-name.muted {
      color: ${theme.colors.grayscale.light1};
      font-style: italic;
    }

    .filter-field {
      width: 100%;

      input {
        width: 100%;
        height: ${theme.gridUnit * 8}px;
        padding: 0 ${theme.gridUnit * 2}px;
        border: 1px solid ${theme.colors.grayscale.light2};
        border-radius: ${theme.gridUnit}px;
        box-sizing: border-box;
      }

      input.error {
        border-color: ${theme.colors.error.base};
      }
    }

    .helper {
      margin-top: ${theme.gridUnit}px;
      font-size: ${theme.typography.sizes.s}px;
      color: ${theme.colors.grayscale.base};
    }
  `}
`;

const getChartId = (report: AlertObject): number | null => {
  if (typeof report.chart_id === 'number' && report.chart_id > 0) {
    return report.chart_id;
  }
  const chartValue = report.chart?.value ?? report.chart?.id;
  if (typeof chartValue === 'number' && chartValue > 0) {
    return chartValue;
  }
  if (typeof chartValue === 'string' && chartValue.trim()) {
    const parsed = Number(chartValue);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }
  return null;
};

const getDefaultFilterDate = (report: AlertObject): string => {
  const extra =
    typeof report.extra === 'string'
      ? (() => {
          try {
            return JSON.parse(report.extra);
          } catch {
            return {};
          }
        })()
      : report.extra || {};
  return extra?.date_column || extra?.filter_date || '';
};

function SendNowModal({ show, reports, onHide, onSend }: SendNowModalProps) {
  const yesterday = useMemo(() => moment().subtract(1, 'day').startOf('day'), []);
  const [asOfDate, setAsOfDate] = useState<Moment>(yesterday);
  const [filterDates, setFilterDates] = useState<Record<number, string>>({});
  const [datasetNames, setDatasetNames] = useState<Record<number, string>>({});
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (!show) {
      return undefined;
    }
    setAsOfDate(moment().subtract(1, 'day').startOf('day'));
    setTouched(false);
    const initial: Record<number, string> = {};
    reports.forEach(report => {
      initial[report.id] = getDefaultFilterDate(report);
    });
    setFilterDates(initial);
    setDatasetNames({});

    let cancelled = false;

    const getDashboardId = (report: AlertObject): number | null => {
      if (typeof report.dashboard_id === 'number' && report.dashboard_id > 0) {
        return report.dashboard_id;
      }
      const dashValue = report.dashboard?.value ?? report.dashboard?.id;
      if (typeof dashValue === 'number' && dashValue > 0) {
        return dashValue;
      }
      if (typeof dashValue === 'string' && dashValue.trim()) {
        const parsed = Number(dashValue);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
      }
      return null;
    };

    const loadDatasetNames = async () => {
      const next: Record<number, string> = {};

      await Promise.all(
        reports.map(async report => {
          const chartId = getChartId(report);
          const dashboardId = getDashboardId(report);

          // Dashboard report: show dashboard title + dataset names
          if (dashboardId && !chartId) {
            try {
              const { json: reportJson } = await SupersetClient.get({
                endpoint: `/api/v1/report/${report.id}`,
              });
              const dashTitle =
                reportJson?.result?.dashboard?.dashboard_title ||
                t('Dashboard #%s', dashboardId);

              let datasetLabel = '';
              try {
                const { json: dsJson } = await SupersetClient.get({
                  endpoint: `/api/v1/dashboard/${dashboardId}/datasets`,
                });
                const names = (dsJson?.result || [])
                  .map(
                    (ds: { table_name?: string; datasource_name?: string }) =>
                      ds.table_name || ds.datasource_name,
                  )
                  .filter(Boolean);
                const unique = Array.from(new Set(names));
                if (unique.length) {
                  datasetLabel =
                    unique.length <= 2
                      ? unique.join(', ')
                      : `${unique.slice(0, 2).join(', ')} +${unique.length - 2}`;
                }
              } catch {
                // ignore dataset lookup errors
              }

              next[report.id] = datasetLabel
                ? t('Dashboard: %s (%s)', dashTitle, datasetLabel)
                : t('Dashboard: %s', dashTitle);
            } catch {
              next[report.id] = t('Dashboard: #%s', dashboardId);
            }
            return;
          }

          if (!chartId) {
            next[report.id] = t('Unknown source');
            return;
          }
          try {
            const { json } = await SupersetClient.get({
              endpoint: `/api/v1/report/${report.id}`,
            });
            const chart = json?.result?.chart || {};
            const name =
              chart.datasource_name ||
              chart.datasource_name_text ||
              chart.table?.table_name;
            if (name) {
              next[report.id] = name;
              return;
            }
            const datasourceId = chart.datasource_id;
            if (datasourceId) {
              const { json: datasetJson } = await SupersetClient.get({
                endpoint: `/api/v1/dataset/${datasourceId}`,
              });
              const tableName =
                datasetJson?.result?.table_name ||
                datasetJson?.result?.datasource_name;
              if (tableName) {
                next[report.id] = tableName;
                return;
              }
            }
            next[report.id] = t('Dataset unavailable');
          } catch {
            next[report.id] = t('Dataset unavailable');
          }
        }),
      );

      if (!cancelled) {
        setDatasetNames(next);
      }
    };

    loadDatasetNames();
    return () => {
      cancelled = true;
    };
  }, [show, reports]);

  const missingFilterDates = reports.filter(
    report => !filterDates[report.id]?.trim(),
  );
  const overMaxBatch = reports.length > SEND_NOW_MAX_BATCH;
  const canSend =
    Boolean(asOfDate) && missingFilterDates.length === 0 && !overMaxBatch;

  const onFilterDateChange =
    (id: number) => (event: ChangeEvent<HTMLInputElement>) => {
      const { value } = event.target;
      setFilterDates(current => ({ ...current, [id]: value }));
    };

  const handleSend = () => {
    setTouched(true);
    if (!canSend || !asOfDate) {
      return;
    }
    onSend({
      as_of_date: asOfDate.format('YYYY-MM-DD'),
      items: reports.map(report => ({
        id: report.id,
        name: report.name || '',
        filter_date: filterDates[report.id].trim(),
      })),
    });
  };

  return (
    <Modal
      show={show}
      onHide={onHide}
      title={t('Send now')}
      primaryButtonName={t('Send')}
      primaryButtonType="primary"
      onHandledPrimaryAction={handleSend}
      disablePrimaryButton={!canSend}
      width="780px"
      destroyOnClose
    >
      <StyledForm>
        <div className="date-row">
          <div className="control-label">
            {t('As of date')}
            <span className="required">*</span>
          </div>
          <DatePicker
            value={asOfDate}
            allowClear={false}
            onChange={value => {
              if (value) {
                setAsOfDate(value);
              }
            }}
            data-test="send-now-date"
          />
          <div className="helper">
            {t(
              'Defaults to yesterday. Max %s reports per send; jobs are staggered to reduce load.',
              SEND_NOW_MAX_BATCH,
            )}
          </div>
          {overMaxBatch && (
            <div className="helper" style={{ color: '#d32f2f' }}>
              {t(
                'Too many reports selected (%s). Please select at most %s.',
                reports.length,
                SEND_NOW_MAX_BATCH,
              )}
            </div>
          )}
        </div>

        <div className="reports-table" data-test="send-now-reports">
          <div className="reports-header">
            <div>{t('Report')}</div>
            <div>{t('Source')}</div>
            <div>
              {t('Filter date column')}
              <span className="required">*</span>
            </div>
          </div>
          <div className="reports-body">
            {reports.map(report => {
              const hasError = touched && !filterDates[report.id]?.trim();
              const datasetLabel = datasetNames[report.id];
              return (
                <div className="report-row" key={report.id}>
                  <div className="cell">
                    <div className="report-name">{report.name}</div>
                  </div>
                  <div className="cell">
                    <div
                      className={`dataset-name${
                        datasetLabel ? '' : ' muted'
                      }`}
                    >
                      {datasetLabel || t('Loading…')}
                    </div>
                  </div>
                  <div className="cell">
                    <div className="filter-field">
                      <input
                        type="text"
                        value={filterDates[report.id] || ''}
                        placeholder={t('e.g. BUSINESS_DATE')}
                        onChange={onFilterDateChange(report.id)}
                        className={hasError ? 'error' : undefined}
                        data-test={`send-now-filter-date-${report.id}`}
                        aria-label={t('Filter date column')}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <div className="helper">
          {t('Filter date column must be a temporal (date) column on the dataset')}
        </div>
      </StyledForm>
    </Modal>
  );
}

export default SendNowModal;
