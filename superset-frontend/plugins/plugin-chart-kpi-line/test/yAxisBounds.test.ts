import transformProps from '../src/plugin/transformProps';

// 3-metric mode keeps the fixture readable: the current value IS the ratio, so
// each row's y-value is stated directly instead of being derived from succ/tot.
const THREE_METRIC_COLS = ['ds', 'kpi', 'cur', 'prev'];

const build = (data: object[]) =>
  transformProps({
    width: 400,
    height: 300,
    formData: {},
    queriesData: [{ data, colnames: THREE_METRIC_COLS }],
    hooks: {},
    datasource: {},
  } as any);

/** Bounds for a set of y-values, fed in as the current-period line. */
const boundsFor = (values: number[]) => {
  const props = build([
    { ds: 'summary', kpi: 90, cur: 90, prev: 90 },
    { ds: 'MTD', kpi: 90, cur: 90, prev: 90 },
    ...values.map((cur, index) => ({ ds: `P${index}`, kpi: cur, cur, prev: cur })),
  ]);
  const { min, max } = props.echartOptions.yAxis as {
    min: number;
    max: number;
  };
  return { min, max };
};

/** Share of the axis the data actually occupies. The point of the formula. */
const dataShare = (values: number[]) => {
  const { min, max } = boundsFor(values);
  const span = Math.max(...values) - Math.min(...values);
  return (span / (max - min)) * 100;
};

test('narrow percentage data fills a useful share of the axis', () => {
  // The old magnitude-based padding gave these ~9%, which read as a flat line.
  expect(dataShare([94, 95, 96])).toBeGreaterThan(50);
  expect(dataShare([90, 92, 93, 94, 95, 96])).toBeGreaterThan(50);
});

test('the share holds regardless of magnitude', () => {
  // Range-driven padding, so small and large numbers scale alike.
  const small = dataShare([2, 5, 3]);
  const large = dataShare([12000, 12500]);
  expect(Math.abs(small - large)).toBeLessThan(5);
});

test('headroom above the data exceeds the room below, for the point labels', () => {
  const values = [94, 95, 96];
  const { min, max } = boundsFor(values);
  const head = max - Math.max(...values);
  const foot = Math.min(...values) - min;

  expect(head).toBeGreaterThan(foot);
});

test('all-positive data never crosses zero', () => {
  expect(boundsFor([2, 5, 3]).min).toBeGreaterThanOrEqual(0);
  expect(boundsFor([0, 0, 0]).min).toBeGreaterThanOrEqual(0);
});

test('negative data is allowed below zero', () => {
  expect(boundsFor([-5, 10]).min).toBeLessThan(0);
});

test('flat and zero data still yield a drawable, non-zero axis', () => {
  // min === max would leave ECharts with nothing to draw.
  for (const values of [[95, 95, 95], [0, 0, 0]]) {
    const { min, max } = boundsFor(values);
    expect(max).toBeGreaterThan(min);
  }
});

test('no data leaves the bounds to ECharts', () => {
  const props = build([
    { ds: 'summary', kpi: 90, cur: 90, prev: 90 },
    { ds: 'MTD', kpi: 90, cur: 90, prev: 90 },
  ]);
  const { min, max } = props.echartOptions.yAxis as {
    min: undefined;
    max: undefined;
  };

  expect(min).toBeUndefined();
  expect(max).toBeUndefined();
});
