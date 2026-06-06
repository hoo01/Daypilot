const KEYS = {
  USER_ID: 'user_id',
  SESSION_ID: 'session_id',
  TODAY_SCHEDULE: 'today_schedule',
  LAST_FEEDBACK_DATE: 'last_feedback_date',
  MOOD_LOG: 'mood_log',
};

function get(key) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function set(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // quota exceeded — swallow
  }
}

function remove(key) {
  localStorage.removeItem(key);
}

export const storage = {
  getUserId: () => get(KEYS.USER_ID),
  setUserId: (v) => set(KEYS.USER_ID, v),

  getSessionId: () => get(KEYS.SESSION_ID),
  setSessionId: (v) => set(KEYS.SESSION_ID, v),

  getTodaySchedule: () => get(KEYS.TODAY_SCHEDULE),
  setTodaySchedule: (v) => set(KEYS.TODAY_SCHEDULE, v),

  getLastFeedbackDate: () => get(KEYS.LAST_FEEDBACK_DATE),
  setLastFeedbackDate: (v) => set(KEYS.LAST_FEEDBACK_DATE, v),

  getMoodLog: () => get(KEYS.MOOD_LOG) || [],
  setMoodLog: (entries) => {
    // rolling window: keep last 30
    const trimmed = entries.slice(-30);
    set(KEYS.MOOD_LOG, trimmed);
  },

  clear: () => {
    Object.values(KEYS).forEach((k) => remove(k));
  },
};
