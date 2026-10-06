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
import { getFreeGridItems, pxToRows } from './freeGridLayout';

const layout = {
  GRID_ID: {
    id: 'GRID_ID',
    type: 'GRID',
    children: ['ROW-1', 'HEADER-1', 'ROW-2'],
  },
  'ROW-1': { id: 'ROW-1', type: 'ROW', children: ['CHART-a', 'COLUMN-1'] },
  'CHART-a': {
    id: 'CHART-a',
    type: 'CHART',
    children: [],
    meta: { width: 6, height: 50 },
  },
  'COLUMN-1': {
    id: 'COLUMN-1',
    type: 'COLUMN',
    children: ['CHART-b', 'MARKDOWN-c'],
    meta: { width: 6 },
  },
  'CHART-b': {
    id: 'CHART-b',
    type: 'CHART',
    children: [],
    meta: { width: 4, height: 25 },
  },
  'MARKDOWN-c': {
    id: 'MARKDOWN-c',
    type: 'MARKDOWN',
    children: [],
    meta: { width: 4, height: 25 },
  },
  'HEADER-1': { id: 'HEADER-1', type: 'HEADER', children: [], meta: {} },
  'ROW-2': { id: 'ROW-2', type: 'ROW', children: ['CHART-d'] },
  'CHART-d': {
    id: 'CHART-d',
    type: 'CHART',
    children: [],
    meta: { width: 4, height: 50, freeGrid: { x: 10, y: 3, w: 7, h: 9 } },
  },
};

test('flattens rows and columns into positioned leaves', () => {
  const items = getFreeGridItems('GRID_ID', layout, 1);
  const byId = Object.fromEntries(items.map(i => [i.id, i]));

  expect(items.map(i => i.id)).toEqual([
    'CHART-a',
    'CHART-b',
    'MARKDOWN-c',
    'HEADER-1',
    'CHART-d',
  ]);
  expect(byId['CHART-a']).toMatchObject({
    x: 0,
    y: 0,
    w: 12,
    depth: 2,
    parentId: 'ROW-1',
  });
  // column children are stacked at the column's x with the column's width
  expect(byId['CHART-b']).toMatchObject({ x: 12, y: 0, w: 12, depth: 3 });
  expect(byId['MARKDOWN-c']).toMatchObject({ x: 12, y: pxToRows(200), w: 12 });
  expect(byId['HEADER-1']).toMatchObject({ x: 0, w: 24, autoHeight: true });
  // saved free positions win over the tree
  expect(byId['CHART-d']).toMatchObject({ x: 10, y: 3, w: 7, h: 9 });
});

test('returns nothing for a missing container', () => {
  expect(getFreeGridItems('NOPE', layout, 1)).toEqual([]);
});
