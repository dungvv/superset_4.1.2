import { t } from '@superset-ui/core';
import { ControlPanelConfig } from '@superset-ui/chart-controls';

const config: ControlPanelConfig = {
  controlPanelSections: [
    {
      label: t('Query'),
      expanded: true,
      controlSetRows: [['x_axis'], ['metrics'], ['adhoc_filters']],
    },
    {
      label: t('KPI Settings'),
      expanded: true,
      controlSetRows: [
        [
          {
            name: 'kpi_title',
            config: {
              type: 'TextControl',
              label: t('KPI Title'),
              renderTrigger: true,
              default: '',
              description: t('Title displayed at the top of the chart'),
            },
          },
        ],
        [
          {
            name: 'detail_url',
            config: {
              type: 'TextControl',
              label: t('Detail URL'),
              renderTrigger: true,
              default: '',
              description: t(
                'When set, clicking the absolute number opens this URL.',
              ),
            },
          },
        ],
        [
          {
            name: 'kpi_group',
            config: {
              type: 'SelectControl',
              label: t('Nhóm KPI'),
              renderTrigger: true,
              default: 'none',
              choices: [
                ['none', t('Không thuộc nhóm')],
                ['common', t('KPI chung')],
                ['key', t('KPI key')],
                ['main', t('KPI chính')],
                ['addon', t('KPI add-on')],
              ],
              description: t(
                'Nhóm dùng để đếm KPI đạt/chưa đạt khi export Word.',
              ),
            },
          },
        ],
        [
          {
            name: 'kpi_goal_direction',
            config: {
              type: 'SelectControl',
              label: t('Điều kiện đạt KPI'),
              renderTrigger: true,
              default: 'greater_than',
              choices: [
                ['greater_than', t('Lớn hơn KPI')],
                ['less_than', t('Nhỏ hơn KPI')],
              ],
              description: t(
                'Chọn KPI đạt khi metric lớn hơn hoặc nhỏ hơn giá trị KPI.',
              ),
            },
          },
        ],
        [
          {
            name: 'big_number_unit',
            config: {
              type: 'TextControl',
              label: t('Đơn vị Big Number'),
              renderTrigger: true,
              default: '',
              placeholder: t('VD: %, s, ms, VNĐ ...'),
              description: t(
                'Đơn vị hiển thị bên cạnh Big Number. Để trống để dùng mặc định ' +
                  '(% cho 5-metric, không đơn vị cho 3-metric). Ở 3-metric, ' +
                  'đơn vị cũng hiển thị ở dòng con số tuyệt đối.',
              ),
            },
          },
        ],
      ],
    },
    {
      label: t('Chart Options'),
      expanded: true,
      controlSetRows: [
        ['color_scheme'],
        [
          {
            name: 'show_legend',
            config: {
              type: 'CheckboxControl',
              label: t('Show Legend'),
              renderTrigger: true,
              default: true,
              description: t('Whether to display the legend'),
            },
          },
        ],
        [
          {
            name: 'zoomable',
            config: {
              type: 'CheckboxControl',
              label: t('Data Zoom'),
              renderTrigger: true,
              default: false,
              description: t('Enable data zoom controls'),
            },
          },
        ],
        ['y_axis_format'],
        [
          {
            name: 'x_axis_title',
            config: {
              type: 'TextControl',
              label: t('X Axis Title'),
              renderTrigger: true,
              default: '',
              description: t('Title for the X axis'),
            },
          },
        ],
        [
          {
            name: 'y_axis_title',
            config: {
              type: 'TextControl',
              label: t('Y Axis Title'),
              renderTrigger: true,
              default: '%',
              description: t('Title for the Y axis'),
            },
          },
        ],
      ],
    },
  ],
  controlOverrides: {
    metrics: {
      label: t('Metrics'),
      description: t(
        '3-metric mode: 1) KPI 2) Kỳ hiện tại value 3) Kỳ trước value. ' +
          '5-metric mode: 1) KPI 2) Kỳ hiện tại Success 3) Kỳ hiện tại Total 4) Kỳ trước Success 5) Kỳ trước Total.',
      ),
    },
    y_axis_format: {
      label: t('Y Axis Format'),
      default: '.1%',
    },
    x_axis: {
      label: t('X Axis Column'),
    },
  },
};

export default config;
