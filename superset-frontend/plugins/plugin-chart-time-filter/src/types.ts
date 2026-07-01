import {
  ChartDataResponseResult,
  ChartProps,
  DataRecord,
  QueryFormData,
  SetDataMaskHook,
} from '@superset-ui/core';

export interface TimeFilterFormData extends QueryFormData {
  time_grain?: string;
  grain_value?: string;
}

export interface TimeFilterChartProps extends ChartProps<TimeFilterFormData> {
  formData: TimeFilterFormData;
  queriesData: ChartDataResponseResult[];
}

export interface TimeFilterVizProps {
  width: number;
  height: number;
  emitCrossFilters?: boolean;
  setDataMask?: SetDataMaskHook;
  formData: TimeFilterFormData;
  data: DataRecord[];
  colnames: string[];
}
