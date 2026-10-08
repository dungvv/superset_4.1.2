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
import {
  createContext,
  lazy,
  FC,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Global } from '@emotion/react';
import { useHistory } from 'react-router-dom';
import { t, useTheme } from '@superset-ui/core';
import { useDispatch, useSelector } from 'react-redux';
import { useToasts } from 'src/components/MessageToasts/withToasts';
import Loading from 'src/components/Loading';
import {
  useDashboard,
  useDashboardCharts,
  useDashboardDatasets,
} from 'src/hooks/apiResources';
import { hydrateDashboard } from 'src/dashboard/actions/hydrate';
import { setDatasources } from 'src/dashboard/actions/datasources';
import injectCustomCss from 'src/dashboard/util/injectCustomCss';

import { LocalStorageKeys, setItem } from 'src/utils/localStorageHelpers';
import { URL_PARAMS } from 'src/constants';
import { getUrlParam } from 'src/utils/urlUtils';
import { setDatasetsStatus } from 'src/dashboard/actions/dashboardState';
import {
  getFilterValue,
  getPermalinkValue,
} from 'src/dashboard/components/nativeFilters/FilterBar/keyValue';
import DashboardContainer from 'src/dashboard/containers/Dashboard';
import { EagerTabLoadingContext } from 'src/dashboard/contexts/EagerTabLoadingContext';
import {
  consumeTabsForReload,
  saveTabsForReload,
} from 'src/dashboard/util/restoreTabsOnReload';

import { nanoid } from 'nanoid';
import { RootState } from '../types';
import { subscribeDashboardMetadataSaved } from '../util/dashboardWriteGuard';
import {
  chartContextMenuStyles,
  filterCardPopoverStyle,
  focusStyle,
  headerStyles,
  chartHeaderStyles,
} from '../styles';
import SyncDashboardState, {
  getDashboardContextLocalStorage,
} from '../components/SyncDashboardState';

export const DashboardPageIdContext = createContext('');

const DashboardBuilder = lazy(
  () =>
    import(
      /* webpackChunkName: "DashboardContainer" */
      /* webpackPreload: true */
      'src/dashboard/components/DashboardBuilder/DashboardBuilder'
    ),
);

const originalDocumentTitle = document.title;

/** Full page reload interval for specific kiosk-style dashboards only. */
const PERIODIC_PAGE_RELOAD_MS = 15 * 60 * 1000;
const PERIODIC_PAGE_RELOAD_CHECK_MS = 60 * 1000;

type DashboardRuntimeConfig = {
  dashboard_ids?: number[];
  eager_tab_dashboard_ids?: number[];
};
const EMPTY_RUNTIME_CONFIG: DashboardRuntimeConfig = {};

const fetchDashboardRuntimeConfig = async (): Promise<DashboardRuntimeConfig> => {
  try {
    const response = await fetch('/api/v1/dashboard/periodic_reload_config/');
    if (!response.ok) return {};
    const data = await response.json();
    return data?.result || data;
  } catch {
    return {};
  }
};

type PageProps = {
  idOrSlug: string;
};

export const DashboardPage: FC<PageProps> = ({ idOrSlug }: PageProps) => {
  const theme = useTheme();
  const dispatch = useDispatch();
  const history = useHistory();
  const dashboardPageId = useMemo(() => nanoid(), []);
  const hasDashboardInfoInitiated = useSelector<RootState, Boolean>(
    ({ dashboardInfo }) =>
      dashboardInfo && Object.keys(dashboardInfo).length > 0,
  );
  const editMode = useSelector<RootState, boolean>(
    ({ dashboardState }) => dashboardState.editMode,
  );
  const activeTabs = useSelector<RootState, string[]>(
    ({ dashboardState }) => dashboardState.activeTabs,
  );
  const directPathToChild = useSelector<RootState, string[]>(
    ({ dashboardState }) => dashboardState.directPathToChild,
  );
  const { addDangerToast } = useToasts();
  const { result: dashboard, error: dashboardApiError } =
    useDashboard(idOrSlug);
  const { result: charts, error: chartsApiError } =
    useDashboardCharts(idOrSlug);
  const {
    result: datasets,
    error: datasetsApiError,
    status,
  } = useDashboardDatasets(idOrSlug);
  const isDashboardHydrated = useRef(false);
  const [runtimeConfig, setRuntimeConfig] = useState<{
    dashboardId: number;
    config: DashboardRuntimeConfig;
  }>({ dashboardId: 0, config: {} });

  const error = dashboardApiError || chartsApiError;
  const readyToRender = Boolean(dashboard && charts);
  const { dashboard_title, css, id = 0 } = dashboard || {};

  useEffect(() => {
    let active = true;
    if (id) {
      fetchDashboardRuntimeConfig().then(config => {
        if (active) setRuntimeConfig({ dashboardId: id, config });
      });
    }
    return () => {
      active = false;
    };
  }, [id]);

  const currentConfig =
    runtimeConfig.dashboardId === id
      ? runtimeConfig.config
      : EMPTY_RUNTIME_CONFIG;
  const eagerTabLoading =
    !editMode && currentConfig.eager_tab_dashboard_ids?.includes(id) === true;

  const tabsRef = useRef({ activeTabs, directPathToChild });
  tabsRef.current = { activeTabs, directPathToChild };

  useEffect(() => {
    if (!id) return undefined;
    const handleBeforeUnload = () => saveTabsForReload(id, tabsRef.current);
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [id]);

  useEffect(() => {
    // mark tab id as redundant when user closes browser tab - a new id will be
    // generated next time user opens a dashboard and the old one won't be reused
    const handleTabClose = () => {
      const dashboardsContexts = getDashboardContextLocalStorage();
      setItem(LocalStorageKeys.DashboardExploreContext, {
        ...dashboardsContexts,
        [dashboardPageId]: {
          ...dashboardsContexts[dashboardPageId],
          isRedundant: true,
        },
      });
    };
    window.addEventListener('beforeunload', handleTabClose);
    return () => {
      window.removeEventListener('beforeunload', handleTabClose);
    };
  }, [dashboardPageId]);

  useEffect(() => {
    dispatch(setDatasetsStatus(status));
  }, [dispatch, status]);

  useEffect(() => {
    if (!id) {
      return undefined;
    }
    return subscribeDashboardMetadataSaved(id, () => {
      window.location.reload();
    });
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line consistent-return
    async function getDataMaskApplied() {
      const permalinkKey = getUrlParam(URL_PARAMS.permalinkKey);
      const nativeFilterKeyValue = getUrlParam(URL_PARAMS.nativeFiltersKey);
      const isOldRison = getUrlParam(URL_PARAMS.nativeFilters);

      let dataMask = nativeFilterKeyValue || {};
      // activeTabs is initialized with undefined so that it doesn't override
      // the currently stored value when hydrating
      let activeTabs: string[] | undefined;
      if (permalinkKey) {
        const permalinkValue = await getPermalinkValue(permalinkKey);
        if (permalinkValue) {
          ({ dataMask, activeTabs } = permalinkValue.state);
        }
      } else if (nativeFilterKeyValue) {
        dataMask = await getFilterValue(id, nativeFilterKeyValue);
      }
      if (isOldRison) {
        dataMask = isOldRison;
      }

      if (readyToRender) {
        const savedTabs = consumeTabsForReload(
          id,
          dashboard?.position_data || {},
        );
        const hasExplicitSelection = Boolean(
          permalinkKey || getUrlParam(URL_PARAMS.dashboardFocusedChart) || window.location.hash,
        );
        if (!hasExplicitSelection && savedTabs) {
          ({ activeTabs } = savedTabs);
        }
        // A permalink only stores activeTabs, but the tab shown by the
        // dashboard (top level tabs included) follows directPathToChild:
        // open the permalink's innermost tab, e.g. for report screenshots.
        let permalinkPath: string[] | undefined;
        if (permalinkKey && activeTabs?.length) {
          const leafTab = activeTabs[activeTabs.length - 1];
          const tabComponent = dashboard?.position_data?.[leafTab];
          if (tabComponent) {
            permalinkPath = [...(tabComponent.parents || []), leafTab];
          }
        }
        if (!isDashboardHydrated.current) {
          isDashboardHydrated.current = true;
        }
        dispatch(
          hydrateDashboard({
            history,
            dashboard,
            charts,
            activeTabs,
            directPathToChild: hasExplicitSelection
              ? permalinkPath
              : savedTabs?.directPathToChild,
            dataMask,
          }),
        );
      }
      return null;
    }
    if (id) getDataMaskApplied();
    // Re-hydrate when switching dashboards in the same SPA tab so
    // dashboardInfo.id cannot stay pointed at a previously opened dashboard.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readyToRender, id]);

  useEffect(() => {
    if (dashboard_title) {
      document.title = dashboard_title;
    }
    return () => {
      document.title = originalDocumentTitle;
    };
  }, [dashboard_title]);

  useEffect(() => {
    if (typeof css === 'string') {
      // returning will clean up custom css
      // when dashboard unmounts or changes
      return injectCustomCss(css);
    }
    return () => { };
  }, [css]);

  useEffect(() => {
    if (datasetsApiError) {
      addDangerToast(
        t('Error loading chart datasources. Filters may not work correctly.'),
      );
    } else {
      dispatch(setDatasources(datasets));
    }
  }, [addDangerToast, datasets, datasetsApiError, dispatch]);

  useEffect(() => {
    if (!id || editMode) {
      return undefined;
    }

    if (!currentConfig.dashboard_ids?.includes(id)) {
      return undefined;
    }

    const lastReloadTime = Date.now();

    const checkAndReload = () => {
      if (Date.now() - lastReloadTime >= PERIODIC_PAGE_RELOAD_MS) {
        window.location.reload();
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        checkAndReload();
      }
    };

    const timer = setInterval(checkAndReload, PERIODIC_PAGE_RELOAD_CHECK_MS);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [id, editMode, currentConfig]);

  if (error) throw error; // caught in error boundary
  if (!readyToRender || !hasDashboardInfoInitiated) return <Loading />;

  return (
    <>
      <Global
        styles={[
          filterCardPopoverStyle(theme),
          headerStyles(theme),
          chartContextMenuStyles(theme),
          focusStyle(theme),
          chartHeaderStyles(theme),
        ]}
      />
      <SyncDashboardState dashboardPageId={dashboardPageId} />
      <DashboardPageIdContext.Provider value={dashboardPageId}>
        <EagerTabLoadingContext.Provider value={eagerTabLoading}>
          <DashboardContainer>
            <DashboardBuilder />
          </DashboardContainer>
        </EagerTabLoadingContext.Provider>
      </DashboardPageIdContext.Provider>
    </>
  );
};

export default DashboardPage;
