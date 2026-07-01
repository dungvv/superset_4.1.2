import { ChartMetadata, ChartPlugin, t, Behavior } from '@superset-ui/core';
import buildQuery from './buildQuery';
import controlPanel from './controlPanel';
import transformProps from './transformProps';
import thumbnail from '../images/thumbnail.png';
import { KpiLineFormData, KpiLineChartProps } from '../types';

const metadata = new ChartMetadata({
  category: t('KPI'),
  description: t(
    'Displays a KPI summary with big number, absolute values, comparison indicators, and a line chart showing Kỳ này, Kỳ trước, and KPI.',
  ),
  name: t('KPI Line Chart'),
  tags: [
    t('KPI'),
    t('Line'),
    t('Percentages'),
    t('Report'),
    t('Advanced-Analytics'),
  ],
  thumbnail,
  behaviors: [Behavior.DrillToDetail, Behavior.InteractiveChart],
  parseMethod: 'json',
});

export default class KpiLineChartPlugin extends ChartPlugin<
  KpiLineFormData,
  KpiLineChartProps
> {
  constructor() {
    super({
      buildQuery,
      controlPanel,
      loadChart: () => import('../KpiLineChart'),
      metadata,
      transformProps,
    });
  }
}
