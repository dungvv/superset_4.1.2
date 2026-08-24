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
  dashboardInfoMatchesUrl,
  getDashboardIdOrSlugFromUrl,
} from './dashboardWriteGuard';

describe('dashboardWriteGuard', () => {
  it('reads numeric id from dashboard URL', () => {
    expect(
      getDashboardIdOrSlugFromUrl('/superset/dashboard/42/'),
    ).toBe('42');
  });

  it('reads slug from dashboard URL', () => {
    expect(
      getDashboardIdOrSlugFromUrl('/superset/dashboard/sales-kpi/'),
    ).toBe('sales-kpi');
  });

  it('allows write when URL id matches dashboardInfo.id', () => {
    expect(
      dashboardInfoMatchesUrl({ id: 42, slug: 'sales-kpi' }, '/superset/dashboard/42/'),
    ).toBe(true);
  });

  it('allows write when URL slug matches dashboardInfo.slug', () => {
    expect(
      dashboardInfoMatchesUrl(
        { id: 42, slug: 'sales-kpi' },
        '/superset/dashboard/sales-kpi/',
      ),
    ).toBe(true);
  });

  it('blocks write when URL is a different dashboard', () => {
    expect(
      dashboardInfoMatchesUrl({ id: 42, slug: 'sales-kpi' }, '/superset/dashboard/99/'),
    ).toBe(false);
  });
});
