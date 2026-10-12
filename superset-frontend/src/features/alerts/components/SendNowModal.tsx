/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
import { styled, t } from '@superset-ui/core';
import Modal from 'src/components/Modal';
import { AlertObject } from '../types';

export type SendNowItemPayload = {
  id: number;
};

// No date and no column: the report runs now exactly as its schedule would
export type SendNowPayload = {
  items: SendNowItemPayload[];
};

interface SendNowModalProps {
  show: boolean;
  reports: AlertObject[];
  onHide: () => void;
  onSend: (payload: SendNowPayload) => void;
}

const StyledForm = styled.div`
  ${({ theme }) => `
    .intro {
      margin-bottom: ${theme.gridUnit * 4}px;
      color: ${theme.colors.grayscale.dark1};
    }

    .reports-table {
      border: 1px solid ${theme.colors.grayscale.light2};
      border-radius: ${theme.gridUnit}px;
      overflow: hidden;
    }

    .reports-header,
    .report-row {
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) 110px minmax(0, 1.6fr);
      column-gap: ${theme.gridUnit * 3}px;
      align-items: center;
      padding: ${theme.gridUnit * 2}px ${theme.gridUnit * 3}px;
    }

    .reports-header {
      background: ${theme.colors.grayscale.light4};
      border-bottom: 1px solid ${theme.colors.grayscale.light2};
      font-size: ${theme.typography.sizes.s}px;
      font-weight: ${theme.typography.weights.bold};
      color: ${theme.colors.grayscale.base};
      text-transform: uppercase;
    }

    .reports-body {
      max-height: ${theme.gridUnit * 80}px;
      overflow-y: auto;
    }

    .report-row + .report-row {
      border-top: 1px solid ${theme.colors.grayscale.light2};
    }

    .report-name {
      font-weight: ${theme.typography.weights.bold};
      word-break: break-word;
    }

    .muted {
      color: ${theme.colors.grayscale.base};
      word-break: break-word;
    }

    .helper {
      margin-top: ${theme.gridUnit * 3}px;
      font-size: ${theme.typography.sizes.s}px;
      color: ${theme.colors.grayscale.base};
    }

  `}
`;

const sourceLabel = (report: AlertObject): string => {
  if (report.dashboard_id || report.dashboard?.value || report.dashboard?.id) {
    return t('Dashboard');
  }
  if (report.chart_id || report.chart?.value || report.chart?.id) {
    return t('Chart');
  }
  return t('Unknown');
};

const recipientTargets = (report: AlertObject): string => {
  const targets = (report.recipients || [])
    .map(recipient => {
      let config: any = recipient.recipient_config_json;
      if (typeof config === 'string') {
        try {
          config = JSON.parse(config);
        } catch {
          config = {};
        }
      }
      return config?.target;
    })
    .filter(Boolean);
  return targets.length ? targets.join(', ') : '-';
};

function SendNowModal({ show, reports, onHide, onSend }: SendNowModalProps) {
  const handleSend = () => {
    if (!reports.length) {
      return;
    }
    onSend({ items: reports.map(report => ({ id: report.id })) });
  };

  return (
    <Modal
      show={show}
      onHide={onHide}
      title={t('Send now')}
      primaryButtonName={t('Send')}
      primaryButtonType="primary"
      onHandledPrimaryAction={handleSend}
      disablePrimaryButton={!reports.length}
      width="720px"
      destroyOnClose
    >
      <StyledForm>
        <div className="intro">
          {t(
            'The report runs now exactly as it does on its schedule (same saved ' +
              'filters, content and recipients). Alerts are sent only when ' +
              'their condition is met.',
          )}
        </div>
        <div className="reports-table" data-test="send-now-reports">
          <div className="reports-header">
            <div>{t('Report')}</div>
            <div>{t('Content')}</div>
            <div>{t('Recipients')}</div>
          </div>
          <div className="reports-body">
            {reports.map(report => (
              <div className="report-row" key={report.id}>
                <div className="report-name">{report.name}</div>
                <div className="muted">{sourceLabel(report)}</div>
                <div className="muted">{recipientTargets(report)}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="helper">
          {t(
            'Any number of reports can be selected: they are queued in small ' +
              'groups, a few seconds apart, to avoid overloading the system.',
          )}
        </div>
      </StyledForm>
    </Modal>
  );
}

export default SendNowModal;
