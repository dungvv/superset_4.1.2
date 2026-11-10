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
/**
 * Upload file business types shown on the page.
 *
 * To add a business type, add its handler on the server
 * (superset/upload_file/handlers/) and append an entry here. The Excel template
 * of "Download template" is built by the server from the handler.
 */
export interface BusinessType {
  value: string;
  label: string;
}

export const BUSINESS_TYPES: BusinessType[] = [{ value: 'VPG', label: 'VPG' }];

export const getBusinessType = (value?: string | null) =>
  BUSINESS_TYPES.find(b => b.value === value);
