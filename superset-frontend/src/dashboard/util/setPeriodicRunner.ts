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
export const stopPeriodicRender = (refreshTimer?: number) => {
  if (refreshTimer) {
    clearTimeout(refreshTimer);
  }
};

interface SetPeriodicRunnerProps {
  interval?: number;
  periodicRender: () => void;
  refreshTimer?: number;
  onTimerScheduled?: (timerId: number) => void;
}

// Drift-corrected chained setTimeout (clearTimeout-friendly via onTimerScheduled).
export default function setPeriodicRunner({
  interval = 0,
  periodicRender,
  refreshTimer,
  onTimerScheduled,
}: SetPeriodicRunnerProps): number {
  stopPeriodicRender(refreshTimer);

  if (interval > 0) {
    let nextTickAt = Date.now() + interval;
    const scheduleNext = () => {
      periodicRender();
      nextTickAt += interval;
      const delay = Math.max(0, nextTickAt - Date.now());
      const timerId = window.setTimeout(scheduleNext, delay);
      onTimerScheduled?.(timerId);
    };
    const initialTimerId = window.setTimeout(scheduleNext, interval);
    onTimerScheduled?.(initialTimerId);
    return initialTimerId;
  }
  return 0;
}
