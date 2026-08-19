import {
  ChartDataResponseResult,
  ChartProps,
  ContextMenuFilters,
  DataRecordValue,
  QueryFormData,
  ValueFormatter,
} from '@superset-ui/core';
import { EChartsCoreOption } from 'echarts/core';

export interface KpiLineDatum {
  [key: string]: DataRecordValue;
}

export type KpiLineFormData = QueryFormData & {
  kpi_title?: string;
  detail_url?: string;
  kpi_group?: 'none' | 'common' | 'key';
  kpiGroup?: 'none' | 'common' | 'key';
  kpi_goal_direction?: 'greater_than' | 'less_than';
  big_number_unit?: string;
  x_axis_title?: string;
  y_axis_title?: string;
  show_legend?: boolean;
  zoomable?: boolean;
};

export interface KpiLineChartProps extends ChartProps<KpiLineFormData> {
  formData: KpiLineFormData;
  queriesData: ChartDataResponseResult[];
}

export type SeriesDatum =
  | [string, number | null]
  | [string, number | null, number, number];

export interface KpiLineVizProps {
  width: number;
  height: number;
  kpiTitle: string;
  detailUrl: string;
  kpiGroup: 'none' | 'common' | 'key';
  currentRatio: number | null;
  currentAbsolute: string;
  showCurrentAbsolute: boolean;
  prevRatio: number | null;
  kpiTarget: number | null;
  bigNumberUnit: string;
  kpiComparison: {
    direction: 'up' | 'down' | 'none';
    value: number;
    noData: boolean;
    isGood?: boolean;
  };
  prevPeriodComparison: {
    direction: 'up' | 'down' | 'none';
    value: number;
    noData: boolean;
    isGood?: boolean;
  };
  monthToDateRatio: number | null;
  monthToDateComparison: {
    direction: 'up' | 'down' | 'none';
    value: number;
    noData: boolean;
    isGood?: boolean;
  };
  currentSeries: SeriesDatum[];
  prevSeries: SeriesDatum[];
  kpiTargetSeries: SeriesDatum[];
  echartOptions: EChartsCoreOption;
  formData: KpiLineFormData;
  onContextMenu?: (
    clientX: number,
    clientY: number,
    filters?: ContextMenuFilters,
  ) => void;
  numberFormatter: ValueFormatter;
}
