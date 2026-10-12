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
import userEvent from '@testing-library/user-event';
import { render, screen } from 'spec/helpers/testing-library';
import SendNowModal from './SendNowModal';
import { AlertObject } from '../types';

const report = (id: number, overrides: Partial<AlertObject> = {}) =>
  ({
    id,
    name: `Report ${id}`,
    chart_id: 0,
    dashboard_id: id,
    force_screenshot: false,
    recipients: [
      {
        type: 'Email',
        recipient_config_json: JSON.stringify({ target: `user${id}@mail.com` }),
      },
    ],
    ...overrides,
  }) as unknown as AlertObject;

test('shows each report with its content and recipients, asks for no date', () => {
  render(
    <SendNowModal
      show
      reports={[report(1), report(2, { dashboard_id: undefined, chart_id: 7 })]}
      onHide={jest.fn()}
      onSend={jest.fn()}
    />,
  );
  expect(screen.getByText('Report 1')).toBeInTheDocument();
  expect(screen.getByText('user1@mail.com')).toBeInTheDocument();
  expect(screen.getByText('Dashboard')).toBeInTheDocument();
  expect(screen.getByText('Chart')).toBeInTheDocument();
  // no date picker and no filter column input any more
  expect(screen.queryByText(/as of date/i)).not.toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
});

test('sends only the report ids', () => {
  const onSend = jest.fn();
  render(
    <SendNowModal
      show
      reports={[report(3), report(4)]}
      onHide={jest.fn()}
      onSend={onSend}
    />,
  );
  userEvent.click(screen.getByRole('button', { name: /^send$/i }));
  expect(onSend).toHaveBeenCalledWith({ items: [{ id: 3 }, { id: 4 }] });
});

test('lets many reports be sent in one go, without a limit', () => {
  const onSend = jest.fn();
  const reports = Array.from({ length: 40 }, (_, i) => report(i + 1));
  render(
    <SendNowModal show reports={reports} onHide={jest.fn()} onSend={onSend} />,
  );
  expect(screen.queryByText(/too many reports/i)).not.toBeInTheDocument();
  userEvent.click(screen.getByRole('button', { name: /^send$/i }));
  expect(onSend).toHaveBeenCalledTimes(1);
  expect(onSend.mock.calls[0][0].items).toHaveLength(40);
});
