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
    },
  ]);
}
