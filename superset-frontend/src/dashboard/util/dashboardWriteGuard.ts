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
 * Prevents dashboard metadata (native filters, colors, …) from being
 * written to the wrong dashboard when several dashboard tabs are open.
 *
 * Each tab has its own Redux store, but a stale SPA hydration can leave
 * dashboardInfo.id pointing at dashboard A while the URL is dashboard B.
 * Every PUT must therefore match the URL, and other tabs of the same
 * dashboard are notified so they reload instead of overwriting.
 */

const DASHBOARD_WRITES_CHANNEL = 'superset-dashboard-writes';
const TAB_ID_KEY = 'superset-dashboard-tab-id';

function getTabId(): string {
  if (typeof sessionStorage === 'undefined') {
    return 'unknown';
  }
  let tabId = sessionStorage.getItem(TAB_ID_KEY);
  if (!tabId) {
    tabId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    sessionStorage.setItem(TAB_ID_KEY, tabId);
  }
  return tabId;
}

export type DashboardWriteTarget = {
  id?: number | string;
  slug?: string | null;
};

export function getDashboardIdOrSlugFromUrl(
  pathname = typeof window !== 'undefined' ? window.location.pathname : '',
): string | null {
  const match = pathname.match(/\/dashboard\/([^/]+)/i);
  if (!match) {
    return null;
  }
  return decodeURIComponent(match[1]);
}

export function dashboardInfoMatchesUrl(
  dashboardInfo: DashboardWriteTarget,
  pathname?: string,
): boolean {
  const fromUrl = getDashboardIdOrSlugFromUrl(pathname);
  if (!fromUrl || dashboardInfo?.id == null) {
    return true;
  }
  if (String(dashboardInfo.id) === fromUrl) {
    return true;
  }
  if (dashboardInfo.slug && dashboardInfo.slug === fromUrl) {
    return true;
  }
  return false;
}

export function notifyDashboardMetadataSaved(id: number | string): void {
  if (typeof BroadcastChannel === 'undefined' || id == null) {
    return;
  }
  try {
    const channel = new BroadcastChannel(DASHBOARD_WRITES_CHANNEL);
    channel.postMessage({
      type: 'dashboard-metadata-saved',
      id: Number(id),
      tabId: getTabId(),
      ts: Date.now(),
    });
    channel.close();
  } catch {
    // BroadcastChannel may be unavailable (older browsers / private mode).
  }
}

export function subscribeDashboardMetadataSaved(
  dashboardId: number | string | undefined,
  onSavedInOtherTab: () => void,
): () => void {
  if (
    typeof BroadcastChannel === 'undefined' ||
    dashboardId == null ||
    dashboardId === 0
  ) {
    return () => undefined;
  }
  let channel: BroadcastChannel;
  try {
    channel = new BroadcastChannel(DASHBOARD_WRITES_CHANNEL);
  } catch {
    return () => undefined;
  }
  const onMessage = (event: MessageEvent) => {
    if (event.data?.type !== 'dashboard-metadata-saved') {
      return;
    }
    if (event.data.tabId === getTabId()) {
      return;
    }
    if (Number(event.data.id) === Number(dashboardId)) {
      onSavedInOtherTab();
    }
  };
  channel.addEventListener('message', onMessage);
  return () => {
    channel.removeEventListener('message', onMessage);
    channel.close();
  };
}
