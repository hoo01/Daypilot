const BASE = '/api';

async function request(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const error = new Error(err.detail || res.statusText);
    error.status = res.status;
    throw error;
  }
  return res.json();
}

export const api = {
  health: () => request('GET', '/health'),

  getScheduleToday: (userId) =>
    request('GET', `/schedule/today?user_id=${encodeURIComponent(userId)}`),

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

  confirmSchedule: (userId, targetDate, proposal, proposalType) =>
    request('POST', '/schedule/confirm', {
      user_id: userId,
      target_date: targetDate,
      proposal,
      proposal_type: proposalType,
    }),

  getAuthUrl: (userId) =>
    request('GET', `/auth/google?user_id=${encodeURIComponent(userId)}`),
};
