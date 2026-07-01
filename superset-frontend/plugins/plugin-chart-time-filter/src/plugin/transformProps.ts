import { TimeFilterChartProps, TimeFilterVizProps } from '../types';

export default function transformProps(
  chartProps: TimeFilterChartProps,
): TimeFilterVizProps {
  const { width, height, formData, emitCrossFilters, hooks, queriesData } =
    chartProps;

  return {
    width,
    height,
    emitCrossFilters,
    setDataMask: hooks?.setDataMask,
    formData,
    data: (queriesData[0]?.data || []) as any[],
    colnames: queriesData[0]?.colnames || [],
  };
}
