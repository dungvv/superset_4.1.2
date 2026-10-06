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
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import GridLayout, { Layout } from 'react-grid-layout';
import {
  addAlpha,
  css,
  FeatureFlag,
  isFeatureEnabled,
  styled,
  t,
} from '@superset-ui/core';
import Icons from 'src/components/Icons';
import { RootState } from 'src/dashboard/types';
import DashboardComponent from 'src/dashboard/containers/DashboardComponent';
import { updateComponents } from 'src/dashboard/actions/dashboardLayout';
import { isCurrentUserBot } from 'src/utils/isBot';
import {
  colsToPx,
  FreeGridItem,
  FREE_GRID_COLUMN_COUNT,
  FREE_GRID_MARGIN,
  FREE_GRID_MIN_H,
  FREE_GRID_MIN_W,
  FREE_GRID_ROW_HEIGHT,
  getFreeGridItems,
  rowsToPx,
} from 'src/dashboard/util/freeGridLayout';

type FreeGridProps = {
  containerId: string;
  // depth the container gives to its direct children
  depth: number;
  isComponentVisible?: boolean;
  onChangeTab?: (...args: any[]) => void;
};

const noop = () => {};

const StyledGrid = styled.div`
  ${({ theme }) => css`
    position: relative;
    width: 100%;

    .react-grid-layout {
      position: relative;
      transition: height 200ms ease;
    }

    .react-grid-item {
      transition: all 200ms ease;
      transition-property: left, top, width, height;
      box-sizing: border-box;

      &.cssTransforms {
        transition-property: transform, width, height;
      }
      &.resizing,
      &.react-draggable-dragging {
        transition: none;
        z-index: 3;
        will-change: transform;
      }
      &.react-grid-placeholder {
        background: ${addAlpha(theme.colors.primary.base, 0.15)};
        border: 1px dashed ${theme.colors.primary.base};
        border-radius: ${theme.borderRadius}px;
        transition-duration: 100ms;
        z-index: 2;
        user-select: none;
      }
    }

    .react-resizable-handle {
      position: absolute;
      width: 16px;
      height: 16px;
      z-index: 4;
      opacity: 0;
      transition: opacity 0.2s;

      &::after {
        content: '';
        position: absolute;
        right: 4px;
        bottom: 4px;
        width: 6px;
        height: 6px;
        border-right: 2px solid ${theme.colors.grayscale.base};
        border-bottom: 2px solid ${theme.colors.grayscale.base};
      }
    }
    .react-resizable-handle-se {
      right: 0;
      bottom: 0;
      cursor: se-resize;
    }
    .react-resizable-handle-e {
      right: 0;
      top: 50%;
      margin-top: -8px;
      cursor: ew-resize;
      &::after {
        border-bottom: none;
      }
    }
    .react-resizable-handle-s {
      left: 50%;
      bottom: 0;
      margin-left: -8px;
      cursor: ns-resize;
      &::after {
        border-right: none;
      }
    }

    .free-grid-item {
      &:hover .react-resizable-handle,
      &:hover .free-grid-item__handle {
        opacity: 1;
      }
    }

    .free-grid-item__handle {
      position: absolute;
      top: 0;
      left: 50%;
      transform: translateX(-50%);
      z-index: 5;
      padding: 0 ${theme.gridUnit * 2}px;
      line-height: 0;
      cursor: move;
      opacity: 0;
      transition: opacity 0.2s;
      background: ${theme.colors.grayscale.light5};
      border: 1px solid ${theme.colors.grayscale.light2};
      border-top: none;
      border-radius: 0 0 ${theme.borderRadius}px ${theme.borderRadius}px;
      color: ${theme.colors.grayscale.base};
    }

    .free-grid-item__content {
      width: 100%;
      height: 100%;

      /* legacy resizable wrappers fill the free grid cell */
      .resizable-container {
        width: 100% !important;
        height: 100% !important;
        max-width: none !important;
        max-height: none !important;
        min-width: 0 !important;
        min-height: 0 !important;
      }
      .resizable-container-handle--right,
      .resizable-container-handle--bottom,
      .resizable-container-handle--bottom-right {
        display: none;
      }
      .dashboard-component-chart-holder,
      .dashboard-markdown {
        height: 100%;
      }
      .dragdroppable {
        height: 100%;
      }
    }

    .free-grid-item__content--auto {
      height: auto;
      .dragdroppable {
        height: auto;
      }
    }
  `}
`;

const useElementWidth = () => {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    setWidth(element.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
};

// same strategy as Row: render charts close to the viewport, unmount far ones
const useIsInView = (ref: React.RefObject<HTMLElement>) => {
  const virtualized =
    isFeatureEnabled(FeatureFlag.DashboardVirtualization) &&
    !isCurrentUserBot();
  const [isInView, setIsInView] = useState(!virtualized);
  useEffect(() => {
    const element = ref.current;
    if (!virtualized || !element) return undefined;
    const enabler = new IntersectionObserver(
      ([entry]) => entry.isIntersecting && setIsInView(true),
      { rootMargin: '100% 0px' },
    );
    const disabler = new IntersectionObserver(
      ([entry]) => !entry.isIntersecting && setIsInView(false),
      { rootMargin: '400% 0px' },
    );
    enabler.observe(element);
    disabler.observe(element);
    return () => {
      enabler.disconnect();
      disabler.disconnect();
    };
  }, [ref, virtualized]);
  return isInView;
};

type CellProps = {
  item: FreeGridItem;
  pxWidth: number;
  pxHeight: number;
  isComponentVisible?: boolean;
  onChangeTab?: (...args: any[]) => void;
  onMeasure: (id: string, height: number) => void;
};

const FreeGridCell = memo(
  ({
    item,
    pxWidth,
    pxHeight,
    isComponentVisible,
    onChangeTab,
    onMeasure,
  }: CellProps) => {
    const ref = useRef<HTMLDivElement>(null);
    const isInView = useIsInView(ref);

    useEffect(() => {
      const element = ref.current;
      if (!item.autoHeight || !element) return undefined;
      const observer = new ResizeObserver(() => {
        onMeasure(item.id, element.offsetHeight);
      });
      observer.observe(element);
      return () => observer.disconnect();
    }, [item.autoHeight, item.id, onMeasure]);

    return (
      <div
        ref={ref}
        className={
          item.autoHeight
            ? 'free-grid-item__content free-grid-item__content--auto'
            : 'free-grid-item__content'
        }
      >
        <DashboardComponent
          id={item.id}
          parentId={item.parentId}
          depth={item.depth}
          index={item.index}
          availableColumnCount={0}
          columnWidth={pxWidth}
          isComponentVisible={isComponentVisible}
          isInView={isInView}
          onResizeStart={noop}
          onResize={noop}
          onResizeStop={noop}
          onChangeTab={onChangeTab}
          freeGrid={{ width: pxWidth, height: pxHeight }}
        />
      </div>
    );
  },
);

const FreeGrid = ({
  containerId,
  depth,
  isComponentVisible,
  onChangeTab,
}: FreeGridProps) => {
  const dispatch = useDispatch();
  const dashboardLayout = useSelector(
    (state: RootState) => state.dashboardLayout.present,
  );
  const editMode = useSelector(
    (state: RootState) => state.dashboardState.editMode,
  );
  const { ref, width } = useElementWidth();
  const [measuredRows, setMeasuredRows] = useState<Record<string, number>>({});

  const items = useMemo(
    () => getFreeGridItems(containerId, dashboardLayout, depth),
    [containerId, dashboardLayout, depth],
  );

  const layout: Layout[] = useMemo(
    () =>
      items.map(item => {
        const h = item.autoHeight ? measuredRows[item.id] ?? item.h : item.h;
        return {
          i: item.id,
          x: item.x,
          y: item.y,
          w: item.w,
          h,
          minW: FREE_GRID_MIN_W,
          minH: item.autoHeight ? h : FREE_GRID_MIN_H,
          maxH: item.autoHeight ? h : undefined,
          resizeHandles: item.autoHeight ? ['e'] : ['se', 'e', 's'],
        };
      }),
    [items, measuredRows],
  );

  const handleMeasure = useCallback((id: string, px: number) => {
    const rows = Math.max(
      1,
      Math.ceil(
        (px + FREE_GRID_MARGIN) / (FREE_GRID_ROW_HEIGHT + FREE_GRID_MARGIN),
      ),
    );
    setMeasuredRows(current =>
      current[id] === rows ? current : { ...current, [id]: rows },
    );
  }, []);

  // persist every position of this grid, so later compaction can't move them
  const persistLayout = useCallback(
    (nextLayout: Layout[]) => {
      const updates: Record<string, any> = {};
      nextLayout.forEach(({ i, x, y, w, h }) => {
        const component = dashboardLayout[i];
        if (!component) return;
        const saved = component.meta?.freeGrid;
        if (
          saved &&
          saved.x === x &&
          saved.y === y &&
          saved.w === w &&
          saved.h === h
        ) {
          return;
        }
        updates[i] = {
          ...component,
          meta: { ...component.meta, freeGrid: { x, y, w, h } },
        };
      });
      if (Object.keys(updates).length) {
        dispatch(updateComponents(updates));
      }
    },
    [dashboardLayout, dispatch],
  );

  const itemsById = useMemo(
    () => Object.fromEntries(items.map(item => [item.id, item])),
    [items],
  );

  return (
    <StyledGrid ref={ref} className="free-grid" data-test="free-grid">
      {width > 0 && (
        <GridLayout
          layout={layout}
          width={width}
          cols={FREE_GRID_COLUMN_COUNT}
          rowHeight={FREE_GRID_ROW_HEIGHT}
          margin={[FREE_GRID_MARGIN, FREE_GRID_MARGIN]}
          containerPadding={[0, 0]}
          compactType="vertical"
          isDraggable={editMode}
          isResizable={editMode}
          draggableHandle=".free-grid-item__handle"
          onDragStop={persistLayout}
          onResizeStop={persistLayout}
          useCSSTransforms
        >
          {layout.map(({ i, w, h }) => (
            <div key={i} className="free-grid-item">
              {editMode && (
                <div
                  className="free-grid-item__handle"
                  title={t('Drag to move')}
                >
                  <Icons.Drag iconSize="l" />
                </div>
              )}
              <FreeGridCell
                item={itemsById[i]}
                pxWidth={colsToPx(w, width)}
                pxHeight={rowsToPx(h)}
                isComponentVisible={isComponentVisible}
                onChangeTab={onChangeTab}
                onMeasure={handleMeasure}
              />
            </div>
          ))}
        </GridLayout>
      )}
    </StyledGrid>
  );
};

export default FreeGrid;
