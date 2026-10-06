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
import { FeatureFlag, isFeatureEnabled } from '@superset-ui/core';
import {
  COLUMN_TYPE,
  DIVIDER_TYPE,
  HEADER_TYPE,
  ROW_TYPE,
  TABS_TYPE,
} from './componentTypes';
import {
  GRID_BASE_UNIT,
  GRID_COLUMN_COUNT,
  GRID_DEFAULT_CHART_WIDTH,
  GRID_GUTTER_SIZE,
} from './constants';

/**
 * Free grid layout.
 *
 * The dashboard tree (ROW -> COLUMN -> CHART) is kept as is in position_json so
 * that the backend, import/export and reports keep working. Every leaf
 * (chart, markdown, header, ...) additionally stores its free position in
 * `meta.freeGrid = { x, y, w, h }`. Leaves without it get a position derived
 * from the tree, so old dashboards look the same on first open.
 */
export const FREE_GRID_COLUMN_COUNT = 24;
export const FREE_GRID_ROW_HEIGHT = GRID_BASE_UNIT;
export const FREE_GRID_MARGIN = GRID_GUTTER_SIZE;
export const FREE_GRID_MIN_W = 2;
export const FREE_GRID_MIN_H = 4;

const COLUMN_RATIO = FREE_GRID_COLUMN_COUNT / GRID_COLUMN_COUNT;

// these components size themselves: their height is measured, not stored
export const AUTO_HEIGHT_TYPES = [HEADER_TYPE, DIVIDER_TYPE, TABS_TYPE];

export type FreeGridPosition = { x: number; y: number; w: number; h: number };

export type FreeGridItem = FreeGridPosition & {
  id: string;
  parentId: string;
  type: string;
  index: number;
  depth: number;
  autoHeight: boolean;
};

type Layout = Record<string, any>;

export const isFreeGridEnabled = () =>
  isFeatureEnabled(FeatureFlag.DashboardFreeGrid);

/** px height (old meta.height * GRID_BASE_UNIT) -> free grid rows */
export const pxToRows = (px: number) =>
  Math.max(
    1,
    Math.round(
      (px + FREE_GRID_MARGIN) / (FREE_GRID_ROW_HEIGHT + FREE_GRID_MARGIN),
    ),
  );

export const rowsToPx = (h: number) =>
  h * FREE_GRID_ROW_HEIGHT + Math.max(0, h - 1) * FREE_GRID_MARGIN;

export const colsToPx = (w: number, containerWidth: number) => {
  const colWidth =
    (containerWidth - FREE_GRID_MARGIN * (FREE_GRID_COLUMN_COUNT - 1)) /
    FREE_GRID_COLUMN_COUNT;
  return Math.floor(w * colWidth + Math.max(0, w - 1) * FREE_GRID_MARGIN);
};

const clampW = (w: number) =>
  Math.min(FREE_GRID_COLUMN_COUNT, Math.max(FREE_GRID_MIN_W, w));

/**
 * Flattens the children of a grid / tab into free grid items.
 * `depth` is the depth the container gives to its direct children.
 */
export function getFreeGridItems(
  containerId: string,
  layout: Layout,
  depth: number,
): FreeGridItem[] {
  const items: FreeGridItem[] = [];
  const container = layout[containerId];
  if (!container) return items;

  // places a node at (x, y) and returns the height it occupies
  const place = (
    id: string,
    parentId: string,
    index: number,
    nodeDepth: number,
    x: number,
    y: number,
    availW: number,
  ): number => {
    const node = layout[id];
    if (!node) return 0;

    if (node.type === ROW_TYPE) {
      let cx = x;
      let maxH = 0;
      node.children.forEach((childId: string, i: number) => {
        const child = layout[childId];
        const childW = Math.min(
          clampW(
            (child?.meta?.width || GRID_DEFAULT_CHART_WIDTH) * COLUMN_RATIO,
          ),
          Math.max(FREE_GRID_MIN_W, x + availW - cx),
        );
        const h = place(childId, id, i, nodeDepth + 1, cx, y, childW);
        cx = Math.min(cx + childW, FREE_GRID_COLUMN_COUNT - FREE_GRID_MIN_W);
        maxH = Math.max(maxH, h);
      });
      return maxH;
    }

    if (node.type === COLUMN_TYPE) {
      let cy = y;
      node.children.forEach((childId: string, i: number) => {
        cy += place(childId, id, i, nodeDepth + 1, x, cy, availW);
      });
      return cy - y;
    }

    const autoHeight = AUTO_HEIGHT_TYPES.includes(node.type);
    const parentType = layout[parentId]?.type;
    const ownWidth =
      !autoHeight && parentType === ROW_TYPE && node.meta?.width
        ? clampW(node.meta.width * COLUMN_RATIO)
        : availW;
    const defaults: FreeGridPosition = {
      x,
      y,
      w: Math.min(ownWidth, availW),
      h: autoHeight ? 2 : pxToRows((node.meta?.height || 50) * GRID_BASE_UNIT),
    };
    const saved = node.meta?.freeGrid as FreeGridPosition | undefined;
    const pos = saved ? { ...defaults, ...saved } : defaults;

    items.push({
      ...pos,
      w: clampW(pos.w),
      x: Math.min(pos.x, FREE_GRID_COLUMN_COUNT - FREE_GRID_MIN_W),
      id,
      parentId,
      type: node.type,
      index,
      depth: nodeDepth,
      autoHeight,
    });
    return defaults.h;
  };

  let y = 0;
  container.children.forEach((childId: string, i: number) => {
    y += place(childId, containerId, i, depth, 0, y, FREE_GRID_COLUMN_COUNT);
  });

  return items;
}
