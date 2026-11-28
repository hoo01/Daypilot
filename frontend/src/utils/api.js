const BASE = '/api';

// The user's IANA timezone: the backend uses it to decide what "today" and "now" mean.
function userTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch {
    return '';
  }
}

async function request(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  const tz = userTimezone();
  if (tz) headers['X-Timezone'] = tz;
  const opts = { method, headers };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    // Domain errors arrive as detail: { code, message } (e.g. 409 invalid_transition)
    const detail = err.detail;
    const isObj = detail && typeof detail === 'object';
    const error = new Error((isObj ? detail.message : detail) || res.statusText);
    error.status = res.status;
    if (isObj) error.code = detail.code;
    throw error;
  }
  return res.json();
}

export const api = {
  health: () => request('GET', '/health'),

  getScheduleToday: (userId) =>
    request('GET', `/schedule/today?user_id=${encodeURIComponent(userId)}`),

  // Full DayPlan { date, active, proposal, version, status }; date defaults to server "today"
  getDayPlan: (userId, date) =>
    request('GET', `/schedule/day?user_id=${encodeURIComponent(userId)}${date ? `&date=${encodeURIComponent(date)}` : ''}`),

  submitFeedback: (userId, date, uncompletedTasks) =>
    request('POST', '/schedule/feedback', {
      user_id: userId,
      date,
      uncompleted_tasks: uncompletedTasks,
    }),

  chat: (userId, message, sessionId) =>
    request('POST', '/chat/', {
      user_id: userId,
      message,
      session_id: sessionId || undefined,
    }),

  // Only identifies the stored proposal + chosen strategy; tasks always come from the server.
  confirmSchedule: (userId, date, proposalId, strategyName) =>
    request('POST', '/schedule/confirm', {
      user_id: userId,
      date,
      proposal_id: proposalId,
      strategy_name: strategyName,
    }),

  getAuthUrl: (userId) =>
    request('GET', `/auth/google?user_id=${encodeURIComponent(userId)}`),
};
