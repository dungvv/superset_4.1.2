import { t, ChartMetadata, ChartPlugin, Behavior } from '@superset-ui/core';
import buildQuery from './buildQuery';
import controlPanel from './controlPanel';
import transformProps from './transformProps';
import { TimeFilterFormData, TimeFilterChartProps } from '../types';

export default class TimeFilterChartPlugin extends ChartPlugin<
  TimeFilterFormData,
  TimeFilterChartProps
> {
  constructor() {
    const metadata = new ChartMetadata({
      category: t('Filters'),
      description: t(
        'A time filter control that lets you select a specific day, month, quarter, year, or custom range and filters other charts in the dashboard.',
      ),
      name: t('Time Filter'),
      tags: [t('Filter'), t('Time'), t('Control')],
      behaviors: [Behavior.InteractiveChart],
    });

    super({
      buildQuery,
      controlPanel,
      loadChart: () => import('../TimeFilterChart'),
      metadata,
      transformProps,
    });
  }
}
