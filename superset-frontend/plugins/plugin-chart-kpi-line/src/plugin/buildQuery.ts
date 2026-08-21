import {
  buildQueryContext,
  ensureIsArray,
  getXAxisColumn,
  isXAxisSet,
  QueryFormData,
} from '@superset-ui/core';

export default function buildQuery(formData: QueryFormData) {
  const xAxisColumns = isXAxisSet(formData)
    ? ensureIsArray(getXAxisColumn(formData))
    : [];

  return buildQueryContext(formData, baseQueryObject => [
    {
      ...baseQueryObject,
      columns: xAxisColumns,
      is_timeseries: false,
      orderby: [],
      // Strip all filters — this chart renders the full dataset as-is
      // so the X-axis always reflects every row unfiltered.
      adhoc_filters: [],
      extras: {},
    },
  ]);
}
