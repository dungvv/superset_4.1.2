import { buildQueryContext, QueryFormData } from '@superset-ui/core';

export default function buildQuery(formData: QueryFormData) {
  return buildQueryContext(formData, () => [
    {
      result_type: 'timegrains',
      columns: [],
      metrics: [],
      orderby: [],
    },
  ]);
}
