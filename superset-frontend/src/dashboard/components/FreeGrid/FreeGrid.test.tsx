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
import { render, screen } from 'spec/helpers/testing-library';
import FreeGrid from './FreeGrid';

jest.mock(
  'src/dashboard/containers/DashboardComponent',
  () =>
    ({ id, freeGrid }: { id: string; freeGrid: { width: number } }) => (
      <div data-test="mock-component">
        {id}:{freeGrid.width}
      </div>
    ),
);

class MockResizeObserver {
  callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }

  observe() {}

  disconnect() {}
}

beforeAll(() => {
  // @ts-ignore
  window.ResizeObserver = MockResizeObserver;
  jest
    .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
    .mockReturnValue({ width: 1000 } as DOMRect);
});

const dashboardLayout = {
  past: [],
  future: [],
  present: {
    GRID_ID: { id: 'GRID_ID', type: 'GRID', children: ['ROW-1'] },
    'ROW-1': { id: 'ROW-1', type: 'ROW', children: ['CHART-a', 'CHART-b'] },
    'CHART-a': {
      id: 'CHART-a',
      type: 'CHART',
      children: [],
      meta: { width: 6, height: 50 },
    },
    'CHART-b': {
      id: 'CHART-b',
      type: 'CHART',
      children: [],
      meta: { width: 6, height: 20 },
    },
  },
};

test('renders every leaf of the tree in the free grid', () => {
  render(<FreeGrid containerId="GRID_ID" depth={1} />, {
    useRedux: true,
    initialState: { dashboardLayout, dashboardState: { editMode: true } },
  });
  const items = screen.getAllByTestId('mock-component');
  expect(items).toHaveLength(2);
  // 12 of 24 columns of a 1000px grid with 16px gutters
  expect(items[0]).toHaveTextContent('CHART-a:492');
  expect(document.querySelectorAll('.free-grid-item__handle')).toHaveLength(2);
});
