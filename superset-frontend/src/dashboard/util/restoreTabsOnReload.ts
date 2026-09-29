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
import { DashboardLayout } from 'src/dashboard/types';
import { TAB_TYPE } from 'src/dashboard/util/componentTypes';

type SavedTabs = {
  activeTabs: string[];
  directPathToChild: string[];
};

const storageKey = (dashboardId: number) => `dashboard-tabs-reload-${dashboardId}`;

export function saveTabsForReload(dashboardId: number, tabs: SavedTabs) {
  try {
    sessionStorage.setItem(storageKey(dashboardId), JSON.stringify(tabs));
  } catch {
    // Storage may be disabled by the browser.
  }
}

export function consumeTabsForReload(
  dashboardId: number,
  layout: DashboardLayout,
): SavedTabs | undefined {
  try {
    const key = storageKey(dashboardId);
    const saved = sessionStorage.getItem(key);
    sessionStorage.removeItem(key);
    if (!saved) return undefined;

    const tabs = JSON.parse(saved) as SavedTabs;
    if (!Array.isArray(tabs.activeTabs) || !Array.isArray(tabs.directPathToChild)) {
      return undefined;
    }

    const validPath = tabs.directPathToChild.every((id, index, path) =>
      index === 0
        ? Boolean(layout[id])
        : layout[path[index - 1]]?.children?.includes(id),
    );
    return {
      activeTabs: tabs.activeTabs.filter(id => layout[id]?.type === TAB_TYPE),
      directPathToChild: validPath ? tabs.directPathToChild : [],
    };
  } catch {
    return undefined;
  }
}
