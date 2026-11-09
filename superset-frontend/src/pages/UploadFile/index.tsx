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
/* The status / source colours below intentionally match the exported Excel file
 * (superset/upload_file/export.py), so they are not taken from the theme. */
/* eslint-disable theme-colors/no-literal-colors */
import { useRef, useState, DragEvent, ReactNode } from 'react';
import { styled, SupersetClient, t } from '@superset-ui/core';
import Button from 'src/components/Button';
import Icons from 'src/components/Icons';
import { Select, Steps } from 'src/components';
import SubMenu from 'src/features/home/SubMenu';
import withToasts from 'src/components/MessageToasts/withToasts';
import History from './History';
import { BUSINESS_TYPES, buildTemplateCsv, getBusinessType } from './template';

const ACCEPTED = ['csv', 'xlsx', 'xls'];
const MAX_SIZE = 5 * 1024 * 1024;
const ROW_OPTIONS = [10, 20, 50].map(n => ({ value: n, label: `${n}` }));

const Content = styled.div`
  ${({ theme }) => `
    margin: 0 ${theme.gridUnit * 4}px ${theme.gridUnit * 3}px;
    background: ${theme.colors.grayscale.light5};
    border: 1px solid ${theme.colors.grayscale.light2};
    border-radius: ${theme.borderRadius}px;
    padding: ${theme.gridUnit * 3}px ${theme.gridUnit * 6}px;

    .steps { max-width: 700px; margin: 0 auto ${theme.gridUnit * 3}px; }
    .footer { display: flex; justify-content: flex-end;
      gap: ${theme.gridUnit * 2}px; margin-top: ${theme.gridUnit * 3}px; }
    .template-row { display: flex; justify-content: space-between;
      align-items: center; gap: ${theme.gridUnit * 3}px;
      .type-select { display: flex; align-items: center;
        gap: ${theme.gridUnit * 2}px; .ant-select { width: 240px; } }
      .type-label { font-weight: ${theme.typography.weights.bold}; }
      margin-bottom: ${theme.gridUnit * 3}px; }
    .note { text-align: right; color: ${theme.colors.error.base};
      margin-top: ${theme.gridUnit * 2}px; font-size: ${
        theme.typography.sizes.s
      }px; }
  `}
`;

const DropZone = styled.div<{ active: boolean }>`
  ${({ theme, active }) => `
    border: 2px dashed ${
      active ? theme.colors.primary.base : theme.colors.grayscale.light1
    };
    background: ${active ? theme.colors.primary.light4 : 'transparent'};
    border-radius: ${theme.borderRadius}px;
    padding: ${theme.gridUnit * 4}px ${theme.gridUnit * 4}px;
    text-align: center;
    transition: all 0.15s ease-in-out;
    cursor: pointer;
    .dz-icon { color: ${
      theme.colors.grayscale.light1
    }; transform: rotate(180deg);
      margin-bottom: ${theme.gridUnit * 2}px; }
    .dz-title { color: ${theme.colors.grayscale.base};
      margin-bottom: ${theme.gridUnit * 3}px; }
    .dz-actions { display: flex; justify-content: center;
      gap: ${theme.gridUnit * 2}px; }
  `}
`;

const FileRow = styled.div`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    gap: ${theme.gridUnit * 3}px;
    padding: ${theme.gridUnit * 3}px ${theme.gridUnit * 4}px;
    border: 1px solid ${theme.colors.grayscale.light2};
    border-radius: ${theme.borderRadius}px;
    background: ${theme.colors.grayscale.light4};
    .name { font-weight: ${theme.typography.weights.bold}; }
    .meta { color: ${theme.colors.grayscale.base}; }
    .spacer { flex: 1; }
    .remove { cursor: pointer; color: ${theme.colors.grayscale.base};
      &:hover { color: ${theme.colors.error.base}; } }
  `}
`;

const TableToolbar = styled.div`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: ${theme.gridUnit * 3}px;
    .title { font-weight: ${theme.typography.weights.bold};
      font-size: ${theme.typography.sizes.l}px; }
    .rows { display: flex; align-items: center; gap: ${theme.gridUnit * 2}px;
      .ant-select { width: 80px; } }
    .summary { color: ${theme.colors.grayscale.base};
      margin-right: ${theme.gridUnit * 4}px; }
  `}
`;

const TableWrap = styled.div`
  ${({ theme }) => `
    overflow: auto;
    max-height: 420px;
    border: 1px solid ${theme.colors.grayscale.light2};
    border-radius: ${theme.borderRadius}px;
    table { border-collapse: collapse; width: 100%; }
    th, td { padding: ${theme.gridUnit * 2}px ${theme.gridUnit * 3}px;
      border-bottom: 1px solid ${theme.colors.grayscale.light2};
      text-align: left; white-space: nowrap; max-width: 260px;
      overflow: hidden; text-overflow: ellipsis; }
    th { position: sticky; top: 0; background: ${theme.colors.grayscale.light4};
      font-weight: ${theme.typography.weights.bold}; }
    tr:last-child td { border-bottom: none; }
    th[data-group='input'] { background: #44546A; color: #fff; }
    th[data-group='reply'] { background: #2E7D32; color: #fff; }
    th[data-group='core'] { background: #ED7D31; color: #fff; }
    th[data-group='bccs'] { background: #7F5539; color: #fff; }
    td[data-group='core'] { background: #FCE4D6; }
    td[data-group='bccs'] { background: #EADBC8; }
    td[data-reply] { font-weight: ${theme.typography.weights.bold};
      text-align: center; }
    td[data-reply='TS'] { background: #C6EFCE; color: #006100; }
    td[data-reply='TA'] { background: #FFEB9C; color: #9C5700; }
    td[data-reply='TF'] { background: #FFC7CE; color: #9C0006; }
  `}
`;

const ResultBanner = styled.div`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    gap: ${theme.gridUnit * 3}px;
    margin-bottom: ${theme.gridUnit * 4}px;
    color: ${theme.colors.success.base};
    font-weight: ${theme.typography.weights.bold};
    .summary-chips { display: flex; gap: ${theme.gridUnit * 2}px;
      margin-left: ${theme.gridUnit * 4}px; }
    .summary-chips span { padding: 0 ${theme.gridUnit * 3}px;
      border-radius: ${theme.borderRadius}px; }
    .summary-chips [data-reply='TS'] { background: #C6EFCE; color: #006100; }
    .summary-chips [data-reply='TA'] { background: #FFEB9C; color: #9C5700; }
    .summary-chips [data-reply='TF'] { background: #FFC7CE; color: #9C0006; }
  `}
`;

interface Table {
  columns: string[];
  rows: string[][];
  // Source of each column ('input' | 'reply' | 'core' | 'bccs'), for the colours
  groups?: string[];
}

interface ProcessResponse {
  valid: boolean;
  errors?: string[];
  id: number | null;
  history_saved: boolean;
  columns: string[];
  groups: string[];
  total_rows: number;
  summary: Record<string, number>;
  preview: string[][];
}

const formatSize = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

const extOf = (name: string) => name.split('.').pop()?.toLowerCase() || '';

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function DataTable({
  title,
  data,
  totalRows,
  extra,
}: {
  title: string;
  data: Table;
  totalRows?: number;
  extra?: ReactNode;
}) {
  const [limit, setLimit] = useState(10);
  return (
    <>
      <TableToolbar>
        <div className="title">{title}</div>
        <div className="rows">
          <span className="summary">
            {t(
              '%s rows, %s columns',
              totalRows ?? data.rows.length,
              data.columns.length,
            )}
          </span>
          <span>{t('Show')}</span>
          <Select
            ariaLabel={t('Rows to display')}
            options={ROW_OPTIONS}
            value={limit}
            onChange={v => setLimit(v as number)}
            allowClear={false}
          />
          <span>{t('rows')}</span>
          {extra}
        </div>
      </TableToolbar>
      <TableWrap>
        <table>
          <thead>
            <tr>
              {data.columns.map((c, i) => (
                // eslint-disable-next-line react/no-array-index-key
                <th key={i} title={c} data-group={data.groups?.[i]}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.slice(0, limit).map((r, i) => (
              // eslint-disable-next-line react/no-array-index-key
              <tr key={i}>
                {data.columns.map((_, j) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <td
                    key={j}
                    title={r[j]}
                    data-group={data.groups?.[j]}
                    data-reply={data.groups?.[j] === 'reply' ? r[j] : undefined}
                  >
                    {r[j]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </>
  );
}

function UploadFile({ addDangerToast, addSuccessToast }: any) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState(0);
  const [businessType, setBusinessType] = useState<string | undefined>();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [source, setSource] = useState<Table | null>(null);
  const [totalRows, setTotalRows] = useState(0);
  const [resultTotal, setResultTotal] = useState(0);
  const [entryId, setEntryId] = useState(0);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [result, setResult] = useState<Table | null>(null);

  const reset = () => {
    setStep(0);
    setFile(null);
    setSource(null);
    setResult(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const selectedType = getBusinessType(businessType);

  const onTypeChange = (value?: string) => {
    setBusinessType(value);
    setFile(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const pick = (f?: File | null) => {
    if (!f) return;
    if (!selectedType) {
      addDangerToast(t('Please select a business type first'));
      return;
    }
    if (!ACCEPTED.includes(extOf(f.name))) {
      addDangerToast(t('Only CSV or Excel files are supported'));
      return;
    }
    if (f.size > MAX_SIZE) {
      addDangerToast(t('File size must not exceed 5 MB'));
      return;
    }
    setFile(f);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files?.[0]);
  };

  const toPreview = async () => {
    if (!file || !selectedType) return;
    setLoading(true);
    try {
      const body = new FormData();
      body.append('file', file);
      body.append('business_type', selectedType.value);
      const { json } = await SupersetClient.post({
        endpoint: '/upload-file/api/validate',
        body,
        stringify: false,
        headers: { Accept: 'application/json' },
      });
      if (!json.valid) {
        addDangerToast((json.errors as string[]).join('. '));
        return;
      }
      setSource({ columns: json.columns, rows: json.preview });
      setTotalRows(json.total_rows);
      setStep(1);
    } catch (error) {
      const response = error as Response;
      const message = await response
        .json?.()
        .then((j: { message?: string }) => j.message)
        .catch(() => undefined);
      addDangerToast(message || t('Unable to read file'));
    } finally {
      setLoading(false);
    }
  };

  const errorMessage = async (error: unknown) => {
    const response = error as Response;
    return response
      .json?.()
      .then((j: { message?: string }) => j.message)
      .catch(() => undefined);
  };

  const process = async () => {
    if (!file || !selectedType) return;
    setLoading(true);
    try {
      const body = new FormData();
      body.append('file', file);
      body.append('business_type', selectedType.value);
      const { json } = await SupersetClient.post({
        endpoint: '/upload-file/api/process',
        body,
        stringify: false,
        headers: { Accept: 'application/json' },
        timeout: 600000,
      });
      const response = json as ProcessResponse;
      if (!response.valid) {
        addDangerToast((response.errors || []).join('. '));
        return;
      }
      setResult({
        columns: response.columns,
        rows: response.preview,
        groups: response.groups,
      });
      setResultTotal(response.total_rows);
      setSummary(response.summary);
      setEntryId(response.id ?? 0);
      setStep(2);
      if (response.history_saved) {
        addSuccessToast(t('File processed successfully'));
      } else {
        addDangerToast(
          t(
            'File processed, but the result could not be saved in the history, so it cannot be downloaded. Please contact the administrator.',
          ),
        );
      }
    } catch (error) {
      addDangerToast(
        (await errorMessage(error)) || t('Failed to process file'),
      );
    } finally {
      setLoading(false);
    }
  };

  const downloadTemplate = () => {
    if (!selectedType) return;
    saveBlob(
      new Blob(['\uFEFF', buildTemplateCsv(selectedType)], {
        type: 'text/csv;charset=utf-8',
      }),
      selectedType.templateFileName,
    );
  };

  const download = (format: 'csv' | 'xlsx') => {
    window.location.href = `/upload-file/api/download/${entryId}?format=${format}`;
  };

  return (
    <>
      <SubMenu name={t('Upload file')} />
      <Content>
        <Steps
          className="steps"
          size="small"
          current={step}
          labelPlacement="vertical"
        >
          <Steps.Step title={t('Select file')} />
          <Steps.Step title={t('Preview data')} />
          <Steps.Step title={t('Result')} />
        </Steps>

        {step === 0 && (
          <>
            <input
              ref={inputRef}
              type="file"
              style={{ display: 'none' }}
              accept=".csv,.xlsx,.xls"
              onChange={e => pick(e.target.files?.[0])}
            />
            <div className="template-row">
              <div className="type-select">
                <span className="type-label">{t('Business type')}</span>
                <Select
                  ariaLabel={t('Business type')}
                  placeholder={t('Select business type')}
                  options={BUSINESS_TYPES.map(b => ({
                    value: b.value,
                    label: b.label,
                  }))}
                  value={businessType}
                  onChange={v => onTypeChange(v as string)}
                />
              </div>
              <Button
                buttonStyle="secondary"
                disabled={!selectedType}
                onClick={downloadTemplate}
              >
                {t('Download template')}
              </Button>
            </div>
            {file ? (
              <FileRow>
                <Icons.File iconSize="xl" />
                <div>
                  <div className="name">{file.name}</div>
                  <div className="meta">{formatSize(file.size)}</div>
                </div>
                <div className="spacer" />
                <Icons.Close
                  className="remove"
                  iconSize="l"
                  role="button"
                  onClick={() => {
                    setFile(null);
                    if (inputRef.current) inputRef.current.value = '';
                  }}
                />
              </FileRow>
            ) : (
              <DropZone
                active={dragging}
                onClick={() =>
                  selectedType
                    ? inputRef.current?.click()
                    : addDangerToast(t('Please select a business type first'))
                }
                onDragOver={e => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
              >
                <Icons.Download className="dz-icon" iconSize="xxl" />
                <div className="dz-title">{t('Drag & drop file here')}</div>
                <Button buttonStyle="primary">{t('Choose file')}</Button>
              </DropZone>
            )}
            <div className="note">
              * {t('Supported: .csv, .xlsx, .xls. Maximum file size 5 MB')}
            </div>
            <div className="footer">
              <Button
                buttonStyle="primary"
                disabled={!file}
                loading={loading}
                onClick={toPreview}
              >
                {t('Next')}
              </Button>
            </div>
          </>
        )}

        {step === 1 && source && (
          <>
            <DataTable
              title={t('Data preview')}
              data={source}
              totalRows={totalRows}
            />
            <div className="footer">
              <Button onClick={() => setStep(0)} disabled={loading}>
                {t('Back')}
              </Button>
              <Button buttonStyle="primary" loading={loading} onClick={process}>
                {t('Process')}
              </Button>
            </div>
          </>
        )}

        {step === 2 && result && (
          <>
            <ResultBanner>
              <Icons.CircleCheckSolid iconSize="xl" />
              {t('Your file has been processed')}
              <span className="summary-chips">
                {['TS', 'TA', 'TF'].map(k => (
                  <span key={k} data-reply={k}>
                    {k}: {summary[k] ?? 0}
                  </span>
                ))}
              </span>
            </ResultBanner>
            <DataTable
              title={t('Result preview')}
              data={result}
              totalRows={resultTotal}
            />
            <div className="footer">
              <Button onClick={reset}>{t('Upload another file')}</Button>
              <Button disabled={!entryId} onClick={() => download('csv')}>
                {t('Download CSV')}
              </Button>
              <Button
                buttonStyle="primary"
                disabled={!entryId}
                onClick={() => download('xlsx')}
              >
                {t('Download Excel')}
              </Button>
            </div>
          </>
        )}
      </Content>
      {step === 0 && <History onError={addDangerToast} />}
    </>
  );
}

export default withToasts(UploadFile);
