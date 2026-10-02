/* ... header Apache License ... */

import { formatLocale, FormatLocaleDefinition } from 'd3-format';
import NumberFormatter from '../NumberFormatter';

/**
 * Format string syntax: `[+].<decimals>[~]k`
 *   .1k   123456   -> 123.5k
 *   .2k   1234567  -> 1.23M
 *   .1~k  120000   -> 120k   (`~` trims insignificant trailing zeros)
 *   +.1k  1500     -> +1.5k  (`+` always shows the sign)
 */
export const SHORT_SCALE_FORMAT_REGEX = /^(\+?)\.(\d{1,2})(~?)k$/;

const UNITS = ['', 'k', 'M', 'B', 'T'];

export function isShortScaleFormat(formatString: string) {
  return SHORT_SCALE_FORMAT_REGEX.test(formatString);
}

export default function createShortScaleFormatter(config: {
  formatString: string;
  description?: string;
  label?: string;
  locale?: FormatLocaleDefinition;
}) {
  const { formatString, description, label, locale } = config;
  const match = SHORT_SCALE_FORMAT_REGEX.exec(formatString);
  if (!match) {
    throw new Error(`Invalid short scale format: ${formatString}`);
  }
  const [, plus, decimals, trim] = match;
  const d3Spec = `${plus}.${decimals}${trim}f`;
  const fixed = (
    locale
      ? formatLocale(locale)
      : formatLocale({
          decimal: '.',
          thousands: ',',
          grouping: [3],
          currency: ['$', ''],
        })
  ).format(d3Spec);
  // Same spec without sign, used to detect rounding up to the next unit
  const roundCheck = Number(decimals);

  const formatFunc = (value: number) => {
    if (!Number.isFinite(value)) {
      return String(value);
    }
    let unitIndex = 0;
    let scaled = value;
    while (Math.abs(scaled) >= 1000 && unitIndex < UNITS.length - 1) {
      scaled /= 1000;
      unitIndex += 1;
    }
    // e.g. 999,950 with 1 decimal rounds to 1000.0k -> should be 1.0M
    const factor = 10 ** roundCheck;
    if (
      Math.abs(Math.round(scaled * factor) / factor) >= 1000 &&
      unitIndex < UNITS.length - 1
    ) {
      scaled /= 1000;
      unitIndex += 1;
    }
    return `${fixed(scaled)}${UNITS[unitIndex]}`;
  };

  return new NumberFormatter({
    id: formatString,
    label: label ?? formatString,
    description,
    formatFunc,
  });
}