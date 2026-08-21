import transformProps from '../src/plugin/transformProps';

const FIVE_METRIC_COLS = ['ds', 'kpi', 'succ', 'tot', 'psucc', 'ptot'];

const row = (ds: string, kpi: number, succ: number, tot: number) => ({
  ds,
  kpi,
  succ,
  tot,
  psucc: 0,
  ptot: 1,
});

const build = (data: object[], colnames = FIVE_METRIC_COLS) =>
  transformProps({
    width: 400,
    height: 300,
    formData: { kpiGoalDirection: 'greater_than' },
    queriesData: [{ data, colnames }],
    hooks: {},
    datasource: {},
  } as any);

const getEchartsXAxis = (data: object[], colnames = FIVE_METRIC_COLS) =>
  (build(data, colnames) as any).echartOptions.xAxis;

test('x-axis labels without spaces are passed through as-is', () => {
  const axis = getEchartsXAxis([
    row('2026-08-10', 90, 100, 105),
    row('2026-08-11', 90, 200, 210),
  ]);
  expect(axis.axisLabel.formatter('2026-08-10')).toBe('2026-08-10');
  expect(axis.axisLabel.formatter('label')).toBe('label');
});

test('x-axis labels with spaces are truncated to the first word', () => {
  const formatter = getEchartsXAxis([
    row('2026-08-10', 90, 100, 105),
  ]).axisLabel.formatter;
  expect(formatter('MON Title')).toBe('MON');
  expect(formatter('TUE午前')).toBe('TUE午前'); // no space → no truncation
  expect(formatter('multi word label here')).toBe('multi');
});

test('tooltip shows full untruncated label', () => {
  const props = build([
    row('2026-08-10', 90, 100, 105),
    row('MON Title', 90, 200, 210),
  ]);
  const tooltipFormatter = (props as any).echartOptions.tooltip.formatter;
  const mockParam = [{ name: 'MON Title', data: [0, 90.48], seriesName: 'Kỳ này' }];
  const html = tooltipFormatter(mockParam);
  expect(html).toContain('MON Title');
  expect(html).not.toContain('...');

  const mockParamNoSpace = [{ name: '2026-08-10', data: [0, 95.24], seriesName: 'Kỳ này' }];
  const htmlNoSpace = tooltipFormatter(mockParamNoSpace);
  expect(htmlNoSpace).toContain('2026-08-10');
});
