import {
  consumeTabsForReload,
  saveTabsForReload,
} from './restoreTabsOnReload';

const layout = {
  ROOT_ID: { id: 'ROOT_ID', children: ['TABS_ID'] },
  TABS_ID: { id: 'TABS_ID', children: ['TAB_1', 'TAB_2'] },
  TAB_1: { id: 'TAB_1', type: 'TAB', children: [] },
  TAB_2: { id: 'TAB_2', type: 'TAB', children: [] },
} as any;

afterEach(() => sessionStorage.clear());

test('restores the selected tab once for the same dashboard', () => {
  const tabs = {
    activeTabs: ['TAB_2'],
    directPathToChild: ['ROOT_ID', 'TABS_ID', 'TAB_2'],
  };
  saveTabsForReload(231, tabs);
  expect(consumeTabsForReload(232, layout)).toBeUndefined();
  expect(consumeTabsForReload(231, layout)).toEqual(tabs);
  expect(consumeTabsForReload(231, layout)).toBeUndefined();
});

test('ignores a selected tab removed from the dashboard layout', () => {
  saveTabsForReload(231, {
    activeTabs: ['TAB_REMOVED'],
    directPathToChild: ['ROOT_ID', 'TABS_ID', 'TAB_REMOVED'],
  });
  expect(consumeTabsForReload(231, layout)).toEqual({
    activeTabs: [],
    directPathToChild: [],
  });
});
