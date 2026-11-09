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
/**
 * Upload file business types.
 *
 * To add a new business type, append an entry to BUSINESS_TYPES with its own
 * columns, descriptions and sample rows. The "Download template" button and
 * the column validation both follow the business type chosen on the page.
 *
 * Generated template CSV layout:
 *   row 1: column names
 *   row 2: column descriptions
 *   rows 3-4: blank
 *   row 5: "Sample data" label
 *   row 6+: sample data (header + rows below)
 */
export interface TemplateColumn {
  name: string;
  description: string;
}

export interface BusinessType {
  value: string;
  label: string;
  templateFileName: string;
  columns: TemplateColumn[];
  sampleRows: string[][];
}

export const BUSINESS_TYPES: BusinessType[] = [
  {
    value: 'VPG',
    label: 'VPG',
    templateFileName: 'File_Upload_Template_VPG.csv',
    columns: [
      { name: 'transID', description: 'Mã giao dịch' },
      { name: 'date', description: 'Ngày giao dịch' },
      { name: 'Phone_NO', description: 'Số điện thoại' },
      { name: 'Type', description: 'Loại giao dịch' },
      { name: 'Amount', description: 'Số tiền' },
      { name: 'Error_code', description: 'Mã lỗi' },
      { name: 'Detail', description: 'Chi tiết lỗi' },
      { name: 'Provider', description: 'Đơn vị cung cấp' },
    ],
    sampleRows: [
      [
        '1057018085',
        '2026-10-14 00:44:05',
        '2099090028',
        'PREPAID',
        '50000',
        '9',
        'Request not response from provider',
        'UNITEL',
      ],
      [
        '1057019308',
        '2026-10-14 00:54:55',
        '2098080320',
        'PREPAID',
        '5000',
        '9',
        'Request not response from provider',
        'UNITEL',
      ],
    ],
  },
];

export const getBusinessType = (value?: string | null) =>
  BUSINESS_TYPES.find(b => b.value === value);

const escapeCsv = (v: string) =>
  /[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;

export function buildTemplateCsv(type: BusinessType): string {
  const names = type.columns.map(c => c.name);
  const blank = names.map(() => '');
  return [
    names,
    type.columns.map(c => c.description),
    blank,
    blank,
    ['Sample data', ...names.slice(1).map(() => '')],
    names,
    ...type.sampleRows,
  ]
    .map(r => r.map(escapeCsv).join(','))
    .join('\r\n');
}
