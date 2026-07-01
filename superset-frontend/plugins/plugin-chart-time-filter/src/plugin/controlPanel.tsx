import { t } from '@superset-ui/core';
import { ControlPanelConfig } from '@superset-ui/chart-controls';

const config: ControlPanelConfig = {
  controlPanelSections: [
    {
      label: t('Time Filter'),
      expanded: true,
      controlSetRows: [
        [
          {
            name: 'time_grain',
            config: {
              type: 'SelectControl',
              label: t('Time Grain'),
              renderTrigger: true,
              default: 'day',
              choices: [
                ['day', t('Ngày')],
                ['month', t('Tháng')],
                ['quarter', t('Quý')],
                ['year', t('Năm')],
                ['custom', t('Custom')],
              ],
              description: t('Select the time grain to filter by'),
            },
          },
        ],
        [
          {
            name: 'grain_value',
            config: {
              type: 'TextControl',
              label: t('Grain Value'),
              renderTrigger: true,
              default: '',
              description: t('Auto-populated by chart UI'),
            },
          },
        ],
      ],
    },
  ],
};

export default config;
