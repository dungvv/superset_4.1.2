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
/* The status colours match the ones of the exported file, not the theme. */
/* eslint-disable theme-colors/no-literal-colors */
import { useCallback, useEffect, useState } from 'react';
import { styled, SupersetClient, t } from '@superset-ui/core';
import moment from 'moment';
import Button from 'src/components/Button';
import { RangePicker } from 'src/components/DatePicker';
import { Input } from 'src/components/Input';
import Pagination from 'src/components/Pagination';
import { Select } from 'src/components';
import Table, { ColumnsType, TableSize } from 'src/components/Table';
import { BUSINESS_TYPES } from './template';

const PAGE_SIZE = 10;

const Body = styled.div`
  ${({ theme }) => `
    margin: 0 ${theme.gridUnit * 4}px ${theme.gridUnit * 4}px;
    background: ${theme.colors.grayscale.light5};
    border: 1px solid ${theme.colors.grayscale.light2};
    border-radius: ${theme.borderRadius}px;
    padding: ${theme.gridUnit * 4}px ${theme.gridUnit * 6}px;
    .title { font-size: ${theme.typography.sizes.l}px;
      font-weight: ${theme.typography.weights.bold};
      margin-bottom: ${theme.gridUnit * 3}px; }
    .filters { display: flex; flex-wrap: nowrap; justify-content: center;
      align-items: center; gap: ${theme.gridUnit * 2}px;
      margin-bottom: ${theme.gridUnit * 3}px; }
    .filters .field { width: 180px; flex: 0 0 auto; }
    .filters .field.range { width: 280px; }
    .filters .ant-select, .filters .ant-input-affix-wrapper,
    .filters .ant-picker { width: 100%; }
    .actions { display: flex; justify-content: center;
      gap: ${theme.gridUnit * 2}px; margin-bottom: ${theme.gridUnit * 4}px; }
    .count { display: block; text-align: center;
      font-weight: ${theme.typography.weights.bold}; }
    .count.ts { color: #006100; }
    .count.ta { color: #9C5700; }
    .count.tf { color: #9C0006; }
    .total { text-align: center; color: ${theme.colors.grayscale.base};
      margin-top: ${theme.gridUnit * 2}px; }
    .empty { text-align: center; color: ${theme.colors.grayscale.base};
      margin-top: ${theme.gridUnit * 2}px; }
    .pager { display: flex; justify-content: center; }
    .status { display: inline-block; padding: 0 ${theme.gridUnit * 2}px;
      border-radius: ${theme.borderRadius}px;
      font-weight: ${theme.typography.weights.bold}; }
    .status.success { background: #C6EFCE; color: #006100; }
    .status.fail { background: #FFC7CE; color: #9C0006; }
    .download { display: flex; gap: ${theme.gridUnit}px; }
    .message { display: inline-block; max-width: 200px; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; }
  `}
`;

interface HistoryRow {
  key: number;
  id: number;
  service: string;
  user: string;
  check_date: string;
  file_name: string;
  result_file_name: string;
  ts: number | null;
  ta: number | null;
  tf: number | null;
  // seconds
  duration: number | null;
  status: 'success' | 'fail' | '';
  fail_message: string;
  can_download: boolean;
  // Empty line that keeps the table at 10 rows
  blank?: boolean;
}

interface Order {
  column: string;
  direction: 'asc' | 'desc';
}

interface Filters {
  service?: string;
  user: string;
  fileName: string;
  // Check Date range, YYYY-MM-DD (Vietnam days)
  dates: [string, string] | null;
  status?: string;
}

const DEFAULT_ORDER: Order = { column: 'check_date', direction: 'desc' };
const NO_FILTERS: Filters = { user: '', fileName: '', dates: null };

const SERVICE_OPTIONS = BUSINESS_TYPES.map(b => ({
  value: b.value,
  label: b.label,
}));
const STATUS_OPTIONS = [
  { value: 'success', label: t('Success') },
  { value: 'fail', label: t('Fail') },
];

const withBlankRows = (rows: HistoryRow[]): HistoryRow[] => [
  ...rows,
  ...Array.from({ length: Math.max(0, PAGE_SIZE - rows.length) }, (_, i) => ({
    key: -(i + 1),
    id: -(i + 1),
    service: '',
    user: '',
    check_date: '',
    file_name: '',
    result_file_name: '',
    ts: null,
    ta: null,
    tf: null,
    duration: null,
    status: '' as const,
    fail_message: '',
    can_download: false,
    blank: true,
  })),
];

const sortOrder = (order: Order, column: string) => {
  if (order.column !== column) return null;
  return order.direction === 'asc' ? ('ascend' as const) : ('descend' as const);
};

const download = (id: number, format: 'csv' | 'xlsx') => {
  window.location.href = `/upload-file/api/download/${id}?format=${format}`;
};

/** The whole history: filters, sortable columns, 10 rows per page. */
export default function History({
  onError,
}: {
  onError: (message: string) => void;
}) {
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [applied, setApplied] = useState<Filters>(NO_FILTERS);
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [order, setOrder] = useState<Order>(DEFAULT_ORDER);
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (nextPage: number, nextOrder: Order, filters: Filters) => {
      const params = new URLSearchParams({
        page: `${nextPage}`,
        order_column: nextOrder.column,
        order_direction: nextOrder.direction,
      });
      if (filters.service) params.set('service', filters.service);
      if (filters.user.trim()) params.set('user', filters.user.trim());
      if (filters.fileName.trim())
        params.set('file_name', filters.fileName.trim());
      if (filters.status) params.set('status', filters.status);
      if (filters.dates) {
        params.set('date_from', filters.dates[0]);
        params.set('date_to', filters.dates[1]);
      }
      setLoading(true);
      try {
        const { json } = await SupersetClient.get({
          endpoint: `/upload-file/api/history?${params.toString()}`,
        });
        setRows(
          (json.result as Omit<HistoryRow, 'key'>[]).map(r => ({
            ...r,
            key: r.id,
          })),
        );
        setCount(json.count);
        setPage(nextPage);
        setOrder(nextOrder);
      } catch (error) {
        // Show why (e.g. 403 when the role lacks "can access on UploadFile")
        const response = error as Response;
        const reason = await response
          .json?.()
          .then((j: { message?: string }) => j.message)
          .catch(() => undefined);
        onError(
          `${t('Unable to load the history')}${
            response.status ? ` (${response.status})` : ''
          }${reason ? `: ${reason}` : ''}`,
        );
      } finally {
        setLoading(false);
      }
    },
    [onError],
  );

  // The panel is shown on the first step only: it loads when it appears
  useEffect(() => {
    load(1, DEFAULT_ORDER, NO_FILTERS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const search = (filters: Filters) => {
    setApplied(filters);
    load(1, order, filters);
  };

  const columns: ColumnsType<HistoryRow> = [
    {
      title: t('No'),
      dataIndex: 'id',
      key: 'no',
      width: 70,
      render: (_: unknown, row: HistoryRow, index: number) =>
        row.blank ? null : (page - 1) * PAGE_SIZE + index + 1,
    },
    {
      title: t('Service'),
      dataIndex: 'service',
      key: 'service',
      sorter: true,
      sortOrder: sortOrder(order, 'service'),
    },
    {
      title: t('User'),
      dataIndex: 'user',
      key: 'user',
      sorter: true,
      sortOrder: sortOrder(order, 'user'),
    },
    {
      title: t('Check Date'),
      dataIndex: 'check_date',
      key: 'check_date',
      sorter: true,
      sortOrder: sortOrder(order, 'check_date'),
    },
    {
      title: t('File name'),
      dataIndex: 'file_name',
      key: 'file_name',
      sorter: true,
      sortOrder: sortOrder(order, 'file_name'),
      render: (name: string) => (
        <span className="message" title={name}>
          {name}
        </span>
      ),
    },
    {
      title: t('Result file name'),
      dataIndex: 'result_file_name',
      key: 'result_file_name',
      render: (name: string) => (
        <span className="message" title={name}>
          {name}
        </span>
      ),
    },
    ...(['ts', 'ta', 'tf'] as const).map(key => ({
      title: key.toUpperCase(),
      dataIndex: key,
      key,
      width: 70,
      sorter: true,
      sortOrder: sortOrder(order, key),
      render: (value: number | null, row: HistoryRow) =>
        row.blank ? null : (
          <span className={`count ${key}`}>{value ?? '-'}</span>
        ),
    })),
    {
      title: t('Duration'),
      dataIndex: 'duration',
      key: 'duration',
      width: 90,
      sorter: true,
      sortOrder: sortOrder(order, 'duration'),
      render: (value: number | null, row: HistoryRow) => {
        if (row.blank) return null;
        return value === null ? '-' : `${value} s`;
      },
    },
    {
      title: t('Status'),
      dataIndex: 'status',
      key: 'status',
      sorter: true,
      sortOrder: sortOrder(order, 'status'),
      render: (status: string) =>
        status ? (
          <span className={`status ${status}`}>
            {status === 'success' ? t('Success') : t('Fail')}
          </span>
        ) : null,
    },
    {
      title: t('Fail message'),
      dataIndex: 'fail_message',
      key: 'fail_message',
      sorter: true,
      sortOrder: sortOrder(order, 'fail_message'),
      render: (message: string) => (
        <span className="message" title={message}>
          {message}
        </span>
      ),
    },
    {
      title: t('Download'),
      key: 'download',
      render: (_: unknown, row: HistoryRow) =>
        // eslint-disable-next-line no-nested-ternary
        row.blank ? null : row.can_download ? (
          <span className="download">
            <Button buttonSize="xsmall" onClick={() => download(row.id, 'csv')}>
              CSV
            </Button>
            <Button
              buttonSize="xsmall"
              buttonStyle="primary"
              onClick={() => download(row.id, 'xlsx')}
            >
              Excel
            </Button>
          </span>
        ) : (
          '-'
        ),
    },
  ];

  const pageCount = Math.max(1, Math.ceil(count / PAGE_SIZE));

  return (
    <Body>
      <div className="title">{t('History')}</div>
      <div className="filters">
        <div className="field">
          <Select
            ariaLabel={t('Service')}
            placeholder={t('Service')}
            options={SERVICE_OPTIONS}
            value={draft.service}
            onChange={v => setDraft({ ...draft, service: v as string })}
            allowClear
          />
        </div>
        <div className="field">
          <Input
            placeholder={t('User')}
            value={draft.user}
            onChange={e => setDraft({ ...draft, user: e.target.value })}
            onPressEnter={() => search(draft)}
            allowClear
          />
        </div>
        <div className="field">
          <Input
            placeholder={t('File name')}
            value={draft.fileName}
            onChange={e => setDraft({ ...draft, fileName: e.target.value })}
            onPressEnter={() => search(draft)}
            allowClear
          />
        </div>
        <div className="field range">
          <RangePicker
            placeholder={[t('From date'), t('To date')]}
            // Controlled by the filters, so Reset clears the picker too
            value={
              draft.dates
                ? [moment(draft.dates[0]), moment(draft.dates[1])]
                : null
            }
            onChange={(_dates, strings) =>
              setDraft({
                ...draft,
                dates:
                  strings[0] && strings[1] ? [strings[0], strings[1]] : null,
              })
            }
          />
        </div>
        <div className="field">
          <Select
            ariaLabel={t('Status')}
            placeholder={t('Status')}
            options={STATUS_OPTIONS}
            value={draft.status}
            onChange={v => setDraft({ ...draft, status: v as string })}
            allowClear
          />
        </div>
      </div>
      <div className="actions">
        <Button buttonStyle="primary" onClick={() => search(draft)}>
          {t('Search')}
        </Button>
        <Button
          onClick={() => {
            setDraft(NO_FILTERS);
            search(NO_FILTERS);
          }}
        >
          {t('Reset')}
        </Button>
      </div>
      <Table<HistoryRow>
        data={withBlankRows(rows)}
        columns={columns}
        size={TableSize.Small}
        loading={loading}
        usePagination={false}
        sticky={false}
        onChange={(_pagination, _filters, sorter) => {
          const single = Array.isArray(sorter) ? sorter[0] : sorter;
          const nextOrder: Order =
            single?.order && single.columnKey
              ? {
                  column: String(single.columnKey),
                  direction: single.order === 'ascend' ? 'asc' : 'desc',
                }
              : DEFAULT_ORDER;
          load(1, nextOrder, applied);
        }}
      />
      {count > 0 && (
        <div className="total">
          {t(
            'Showing %s-%s of %s',
            (page - 1) * PAGE_SIZE + 1,
            Math.min(page * PAGE_SIZE, count),
            count,
          )}
        </div>
      )}
      {!loading && count === 0 && (
        <div className="empty">{t('No history found')}</div>
      )}
      <div className="pager">
        <Pagination
          totalPages={pageCount}
          currentPage={page}
          onChange={(p: number) => load(p, order, applied)}
          hideFirstAndLastPageLinks
        />
      </div>
    </Body>
  );
}
