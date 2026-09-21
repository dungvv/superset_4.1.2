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
import { ChangeEvent, FunctionComponent } from 'react';
import { styled, t } from '@superset-ui/core';
import { Select } from 'src/components';
import { StyledInputContainer } from '../AlertReportModal';

const StyledDependencyCheck = styled.div`
  ${({ theme }) => `
    .input-container {
      textarea {
        height: auto;
        min-height: ${theme.gridUnit * 16}px;
        max-height: ${theme.gridUnit * 40}px;
        overflow-y: auto;
        resize: vertical;
      }

      .helper {
        margin-top: ${theme.gridUnit * 2}px;
        font-size: ${theme.typography.sizes.s}px;
        color: ${theme.colors.grayscale.base};
      }
    }
  `}
`;

const DEPENDENCY_CHECK_OPTIONS = [
  { value: 'disabled', label: t('Disabled') },
  { value: 'enabled', label: t('Enabled') },
];

export interface DependencyCheckProps {
  enabled: boolean;
  tables: string;
  onEnabledChange: (enabled: boolean) => void;
  onTablesChange: (tables: string) => void;
}

const DependencyCheck: FunctionComponent<DependencyCheckProps> = ({
  enabled,
  tables,
  onEnabledChange,
  onTablesChange,
}) => {
  const onSelectChange = (value: string) => {
    onEnabledChange(value === 'enabled');
  };

  const onTextareaChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    onTablesChange(event.target.value);
  };

  return (
    <StyledDependencyCheck>
      <StyledInputContainer>
        <div className="control-label">{t('Dependency check')}</div>
        <div className="input-container">
          <Select
            ariaLabel={t('Dependency check')}
            onChange={onSelectChange}
            value={enabled ? 'enabled' : 'disabled'}
            options={DEPENDENCY_CHECK_OPTIONS}
            placeholder={t('Select option')}
          />
        </div>
      </StyledInputContainer>
      {enabled && (
        <StyledInputContainer>
          <div className="control-label">{t('Table names')}</div>
          <div className="input-container">
            <textarea
              name="dependency_tables"
              data-test="dependency-tables"
              value={tables}
              placeholder={t('Enter table names')}
              onChange={onTextareaChange}
            />
          </div>
          <div className="input-container">
            <div className="helper">
              {t('Table names are separated by "," or ";"')}
            </div>
          </div>
        </StyledInputContainer>
      )}
    </StyledDependencyCheck>
  );
};

export default DependencyCheck;
