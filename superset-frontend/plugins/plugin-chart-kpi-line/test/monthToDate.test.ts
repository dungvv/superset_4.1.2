import transformProps from '../src/plugin/transformProps';

const FIVE_METRIC_COLS = ['ds', 'kpi', 'succ', 'tot', 'psucc', 'ptot'];

const row = (
  ds: string,
  kpi: number,
  succ: number,
  tot: number,
  psucc = 0,
  ptot = 1,
) => ({ ds, kpi, succ, tot, psucc, ptot });

const build = (data: object[], colnames = FIVE_METRIC_COLS) =>
  transformProps({
    width: 400,
    height: 300,
    formData: { kpiGoalDirection: 'greater_than' },
    queriesData: [{ data, colnames }],
    hooks: {},
    datasource: {},
  } as any);

test('month-to-date ratio comes from row[1] and is compared against KPI', () => {
  const props = build([
    row('summary', 90, 950, 1000), // row[0]: KPI + current period
    row('MTD', 90, 3702, 3938), // row[1]: month-to-date
    row('W1', 90, 100, 105),
  ]);

  expect(props.monthToDateRatio).toBeCloseTo(94.01, 2);
  expect(props.monthToDateComparison.noData).toBe(false);
  expect(props.monthToDateComparison.direction).toBe('up');
  expect(props.monthToDateComparison.isGood).toBe(true);
  // compared against KPI (90), not against the current period
  expect(props.monthToDateComparison.value).toBeCloseTo(4.01, 2);
});

test('falling short of KPI reads as down/not good', () => {
  const props = build([
    row('summary', 95, 950, 1000),
    row('MTD', 95, 900, 1000), // 90% vs KPI 95
  ]);

  expect(props.monthToDateComparison.direction).toBe('down');
  expect(props.monthToDateComparison.isGood).toBe(false);
  expect(props.monthToDateComparison.value).toBeCloseTo(5, 2);
});

test('less_than goal direction flips what counts as good', () => {
  const props = transformProps({
    width: 400,
    height: 300,
    formData: { kpiGoalDirection: 'less_than' },
    queriesData: [
      {
        data: [row('summary', 95, 950, 1000), row('MTD', 95, 900, 1000)],
        colnames: FIVE_METRIC_COLS,
      },
    ],
    hooks: {},
    datasource: {},
  } as any);

  expect(props.monthToDateComparison.isGood).toBe(true);
});

test('three-metric mode reads the raw value instead of a ratio', () => {
  const props = build(
    [
      { ds: 'summary', kpi: 90, cur: 93, prev: 88 },
      { ds: 'MTD', kpi: 90, cur: 94, prev: 89 },
    ],
    ['ds', 'kpi', 'cur', 'prev'],
  );

  expect(props.monthToDateRatio).toBe(94);
  expect(props.monthToDateComparison.direction).toBe('up');
  expect(props.showCurrentAbsolute).toBe(false);
});

test('no row[1] means no data, not a crash or a zero', () => {
  const props = build([row('summary', 90, 950, 1000)]);

  expect(props.monthToDateRatio).toBeNull();
  expect(props.monthToDateComparison.noData).toBe(true);
});

test('the line skips both summary rows and starts at row[2]', () => {
  const props = build([
    row('summary', 90, 950, 1000),
    row('MTD', 90, 3702, 3938),
    row('W1', 90, 100, 105),
    row('W2', 90, 200, 210),
  ]);

  expect(props.currentSeries.map(datum => datum[0])).toEqual(['W1', 'W2']);
  // the month-to-date row must not become a point on the line
  expect(props.currentSeries.map(datum => datum[0])).not.toContain('MTD');
  expect(props.prevSeries).toHaveLength(2);
  expect(props.showCurrentAbsolute).toBe(true);
});

test('only summary rows means an empty line, and still a valid MTD figure', () => {
  const props = build([
    row('summary', 90, 950, 1000),
    row('MTD', 90, 3702, 3938),
  ]);

  expect(props.currentSeries).toHaveLength(0);
  expect(props.monthToDateRatio).toBeCloseTo(94.01, 2);
});

test('MTD ratio rounds to 2dp, not silently flattened to 100', () => {
  const props = build([
    row('summary', 90, 950, 1000),
    row('MTD', 90, 1217397, 1217505),
  ]);

  expect(props.monthToDateRatio).toBe(99.99);
});

test('a gap that rounds to 100 is capped at 99.99, never a false 100%', () => {
  const props = build([
    row('summary', 90, 950, 1000),
    row('MTD', 90, 999999, 1000000), // 99.9999% -> would round to 100
  ]);

  expect(props.monthToDateRatio).toBe(99.99);
});

test('zero denominator means nothing failed, so 100%', () => {
  const props = build([
    row('summary', 90, 950, 1000),
    row('MTD', 90, 0, 0),
  ]);

  expect(props.monthToDateRatio).toBe(100);
  expect(props.monthToDateComparison.noData).toBe(false);
  expect(props.monthToDateComparison.isGood).toBe(true);
});

// Grain day/month leaves MTD cur/tot as NULL; that must read as no-data, not
// silently floor to 100 via computeRatio's zero-denominator rule.
test('null MTD cells read as no-data, not 100', () => {
  const props = build([
    { ds: 'summary', kpi: 90, succ: 950, tot: 1000, psucc: 0, ptot: 1 },
    { ds: 'MTD', kpi: 90, succ: null, tot: null, psucc: null, ptot: null },
  ]);

  expect(props.monthToDateRatio).toBeNull();
  expect(props.monthToDateComparison.noData).toBe(true);
});

// The UI rounds to 2dp, so a ratio that only differs beyond that must read as
// unchanged — otherwise the "Không đổi" branch is unreachable for real data.
test('a difference invisible at 2dp counts as unchanged', () => {
  const props = build([row('summary', 95, 6650, 7000)]); // 95.0000...% vs KPI 95

  expect(props.kpiComparison.direction).toBe('none');

  const almost = build([row('summary', 95, 66501, 70000)]); // 95.0014%
  expect(almost.kpiComparison.direction).toBe('none');
});

test('line value labels thin out to every 3rd point past 15 points', () => {
  const labelAt = (pointCount: number, dataIndex: number) => {
    const props = build([
      row('summary', 90, 950, 1000),
      row('MTD', 90, 950, 1000),
      ...Array.from({ length: pointCount }, (_, i) =>
        row(`P${i}`, 90, 90 + i, 100),
      ),
    ]);
    const [currentSeries] = (props.echartOptions as any).series;
    return currentSeries.label.formatter({
      data: currentSeries.data[dataIndex],
      dataIndex,
    });
  };

  expect(labelAt(15, 1)).not.toBe('');
  expect(labelAt(16, 1)).toBe('');
  expect(labelAt(16, 3)).not.toBe('');
});
