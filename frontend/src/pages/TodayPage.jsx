import { useEffect, useState, useRef } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { api } from '../utils/api';
import { storage } from '../utils/storage';
import { getDailyQuote } from '../utils/quotes';
import TaskCard from '../components/TaskCard';
import MoodTrack from '../components/MoodTrack';
import Toast from '../components/Toast';

const MOCK_TASKS = [
  {
    task_id: 'mock_1',
    title: 'Morning reset and plan review',
    start_time: new Date().toISOString().slice(0, 10) + 'T07:50:00',
    end_time:   new Date().toISOString().slice(0, 10) + 'T08:30:00',
    type: 'routine',
    notes: 'A quiet start with health-aware pacing and low cognitive load.',
  },
  {
    task_id: 'mock_2',
    title: 'Deep work block',
    start_time: new Date().toISOString().slice(0, 10) + 'T09:30:00',
    end_time:   new Date().toISOString().slice(0, 10) + 'T11:00:00',
    type: 'deep_work',
    notes: 'Single-focus window for priority work before the first context switch.',
  },
  {
    task_id: 'mock_3',
    title: 'Go to the gym',
    start_time: new Date().toISOString().slice(0, 10) + 'T11:15:00',
    end_time:   new Date().toISOString().slice(0, 10) + 'T12:30:00',
    type: 'workout',
    notes: 'USC Viterbi → LA Fitness Downtown · 18 min drive',
    geo_segment: {
      origin: 'USC Viterbi',
      destination: 'LA Fitness Downtown',
      duration_text: '18 min drive',
      maps_url: 'https://www.google.com/maps',
    },
  },
  {
    task_id: 'mock_4',
    title: 'Lunch and light walk',
    start_time: new Date().toISOString().slice(0, 10) + 'T13:30:00',
    end_time:   new Date().toISOString().slice(0, 10) + 'T14:30:00',
    type: 'break',
    notes: 'Recovery window before the afternoon workload resumes.',
  },
  {
    task_id: 'mock_5',
    title: 'Follow-up and responses',
    start_time: new Date().toISOString().slice(0, 10) + 'T15:00:00',
    end_time:   new Date().toISOString().slice(0, 10) + 'T16:00:00',
    type: 'routine',
    notes: 'Short admin batch with a low-friction task stack.',
  },
  {
    task_id: 'mock_6',
    title: 'Planning check-in',
    start_time: new Date().toISOString().slice(0, 10) + 'T17:20:00',
    end_time:   new Date().toISOString().slice(0, 10) + 'T17:50:00',
    type: 'routine',
    notes: 'Let DayPilot decide whether anything should move before evening.',
  },
  {
    task_id: 'mock_7',
    title: 'Recovery and wind-down',
    start_time: new Date().toISOString().slice(0, 10) + 'T19:00:00',
    end_time:   new Date().toISOString().slice(0, 10) + 'T20:30:00',
    type: 'break',
    notes: 'Keep the evening light to protect the next day\'s energy curve.',
  },
];

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

export default function TodayPage() {
  const navigate = useNavigate();
  const { openAgentDrawer } = useOutletContext();
  const { tasks, setTasks } = useStore();
  const [doneMap, setDoneMap] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(true);
  const quote = useRef(getDailyQuote()).current;

  const lastFeedbackDate = storage.getLastFeedbackDate();
  const feedbackDone = lastFeedbackDate === todayISO();

  useEffect(() => {
    const userId = storage.getUserId();
    async function load() {
      try {
        const cached = storage.getTodaySchedule();
        if (cached) {
          setTasks(cached);
          setLoading(false);
        }
        const res = await api.getScheduleToday(userId);
        // res expected to be an array of tasks
        const list = Array.isArray(res) ? res : res.tasks || [];
        const sorted = list.sort((a, b) =>
          (a.start_time || '').localeCompare(b.start_time || '')
        );
        setTasks(sorted);
        storage.setTodaySchedule(sorted);
      } catch {
        if (!tasks.length) {
          setTasks(MOCK_TASKS);
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // handle /today?user_id=xxx callback from OAuth
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const uid = params.get('user_id');
    if (uid) {
      storage.setUserId(uid);
      navigate('/today', { replace: true });
    }
  }, []);

  function toggleDone(taskId) {
    setDoneMap((prev) => ({ ...prev, [taskId]: !prev[taskId] }));
  }

  async function handleSubmitFeedback() {
    if (feedbackDone || submitting) return;
    const userId = storage.getUserId();
    const uncompleted = tasks
      .filter((t) => !doneMap[t.task_id])
      .map((t) => ({ title: t.title, scheduled_time: t.start_time }));
    setSubmitting(true);
    try {
      const res = await api.submitFeedback(userId, todayISO(), uncompleted);
      storage.setLastFeedbackDate(todayISO());
      setToast(res.message || 'Progress submitted!');
    } catch {
      setToast('Could not submit. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  const displayTasks = tasks.length ? tasks : MOCK_TASKS;
  const dateLabel = new Intl.DateTimeFormat('en-US', {
    weekday: 'short', month: 'short', day: 'numeric',
  }).format(new Date());

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr) 340px',
        gap: '16px',
        height: '100%',
        minWidth: 0,
      }}
    >
      {/* ── main column ── */}
      <div
        style={{
          borderRadius: 'var(--radius-xl)',
          border: '1px solid rgba(255,255,255,0.66)',
          background: 'rgba(255,255,255,0.38)',
          backdropFilter: 'var(--glass)',
          boxShadow: 'var(--shadow-soft)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {/* date + quote header */}
        <div style={{ padding: '20px 20px 0' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              gap: '12px',
              marginBottom: '6px',
            }}
          >
            <h1
              style={{
                fontSize: '22px',
                fontWeight: 700,
                letterSpacing: '-0.05em',
                margin: 0,
                color: 'var(--text)',
              }}
            >
              {dateLabel}
            </h1>
            <span
              style={{
                fontSize: '12px',
                color: 'var(--muted)',
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
              }}
            >
              Today
            </span>
          </div>
          <p
            style={{
              fontSize: '13px',
              color: 'var(--muted)',
              fontStyle: 'italic',
              lineHeight: 1.6,
              margin: '0 0 16px',
            }}
          >
            {quote}
          </p>

          {/* schedule header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-end',
              justifyContent: 'space-between',
              gap: '12px',
              paddingBottom: '12px',
              borderBottom: '1px solid var(--line)',
            }}
          >
            <div>
              <h2
                style={{
                  margin: 0,
                  fontSize: '16px',
                  fontWeight: 700,
                  letterSpacing: '-0.05em',
                }}
              >
                Scheduled tasks
              </h2>
              <span style={{ color: 'var(--muted)', fontSize: '11px' }}>
                Sorted by time
              </span>
            </div>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '8px 12px',
                borderRadius: '999px',
                background: 'rgba(255,255,255,0.56)',
                border: '1px solid rgba(21,29,25,0.08)',
                color: '#2c3531',
                fontSize: '12px',
                boxShadow: '0 8px 22px rgba(24,30,27,0.04)',
              }}
            >
              All tasks · Today
            </div>
          </div>
        </div>

        {/* scrollable task list */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            padding: '14px 20px',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
          }}
        >
          {loading && !displayTasks.length ? (
            <p style={{ color: 'var(--muted)', fontSize: '13px', textAlign: 'center' }}>
              Loading schedule...
            </p>
          ) : (
            displayTasks.map((task) => (
              <TaskCard
                key={task.task_id}
                task={{ ...task, done: Boolean(doneMap[task.task_id]) }}
                onToggle={() => toggleDone(task.task_id)}
              />
            ))
          )}
        </div>

        {/* bottom compose + submit */}
        <div
          style={{
            padding: '14px 16px 16px',
            background:
              'linear-gradient(180deg, rgba(242,246,240,0), rgba(242,246,240,0.78) 18%, rgba(242,246,240,0.97))',
            borderTop: '1px solid rgba(21,29,25,0.05)',
          }}
        >
          {/* agent compose bar */}
          <div
            onClick={openAgentDrawer}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && openAgentDrawer()}
            aria-label="Open DayPilot agent mode"
            style={{
              borderRadius: '22px',
              border: '1px solid rgba(255,255,255,0.72)',
              background: 'linear-gradient(180deg, rgba(255,255,255,0.66), rgba(255,255,255,0.42))',
              boxShadow: '0 18px 38px rgba(24,30,27,0.06)',
              padding: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              backdropFilter: 'blur(18px) saturate(130%)',
              cursor: 'text',
              marginBottom: '10px',
            }}
          >
            <input
              className="compose-input"
              placeholder="Ask DayPilot to adjust, explain, or plan..."
              readOnly
              style={{
                flex: 1,
                border: 0,
                outline: 'none',
                background: 'transparent',
                color: 'var(--text)',
                fontSize: '14px',
                letterSpacing: '0.01em',
                cursor: 'text',
              }}
            />
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); openAgentDrawer(); }}
              style={{
                width: '42px',
                height: '42px',
                borderRadius: '16px',
                border: 0,
                background: 'linear-gradient(135deg, #161d1b, #36423c)',
                color: 'white',
                boxShadow: '0 12px 24px rgba(24,30,27,0.16)',
                cursor: 'pointer',
                display: 'grid',
                placeItems: 'center',
                fontSize: '16px',
                flexShrink: 0,
              }}
            >
              ↑
            </button>
          </div>

          {/* submit feedback */}
          <button
            onClick={handleSubmitFeedback}
            disabled={feedbackDone || submitting}
            style={{
              width: '100%',
              padding: '13px',
              borderRadius: '16px',
              border: 0,
              background:
                feedbackDone
                  ? 'rgba(21,29,25,0.08)'
                  : 'linear-gradient(135deg, #161d1b, #36423c)',
              color: feedbackDone ? 'var(--muted)' : 'white',
              fontSize: '14px',
              fontWeight: 600,
              cursor: feedbackDone || submitting ? 'not-allowed' : 'pointer',
              boxShadow: feedbackDone ? 'none' : '0 12px 24px rgba(24,30,27,0.14)',
              opacity: submitting ? 0.7 : 1,
              transition: '160ms ease',
            }}
          >
            {feedbackDone
              ? '✓ Progress submitted for today'
              : submitting
              ? 'Submitting...'
              : "Submit today's progress"}
          </button>
        </div>

        {/* toast */}
        {toast && (
          <Toast message={toast} onDismiss={() => setToast(null)} />
        )}
      </div>

      {/* ── right sidebar ── */}
      <aside
        style={{
          borderRadius: 'var(--radius-xl)',
          border: '1px solid rgba(255,255,255,0.66)',
          background: 'rgba(255,255,255,0.38)',
          backdropFilter: 'var(--glass)',
          boxShadow: 'var(--shadow-soft)',
          padding: '16px',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '14px',
        }}
      >
        {/* Today at a glance */}
        <section
          style={{
            borderRadius: 'var(--radius-lg)',
            border: '1px solid rgba(255,255,255,0.72)',
            background: 'linear-gradient(180deg, rgba(255,255,255,0.56), rgba(255,255,255,0.30))',
            boxShadow: '0 14px 34px rgba(24,30,27,0.05)',
            padding: '16px',
            backdropFilter: 'blur(18px) saturate(130%)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '12px' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 700, letterSpacing: '-0.05em' }}>
                Today at a glance
              </h3>
              <p style={{ margin: '4px 0 0', color: 'var(--muted)', fontSize: '12px' }}>
                Quiet signals for your day.
              </p>
            </div>
          </div>
          {[
            { label: 'Commute risk', pct: 28, value: 'Low' },
            { label: 'Focus window', pct: 78, value: 'Strong' },
            { label: 'Task density', pct: 62, value: 'Medium' },
          ].map(({ label, pct, value }) => (
            <div
              key={label}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '12px',
                fontSize: '12px',
                color: '#31403a',
                marginBottom: '10px',
              }}
            >
              <span style={{ whiteSpace: 'nowrap' }}>{label}</span>
              <div
                style={{
                  flex: 1,
                  height: '9px',
                  borderRadius: '999px',
                  background: 'rgba(21,29,25,0.08)',
                  overflow: 'hidden',
                  margin: '0 8px',
                }}
              >
                <span
                  style={{
                    display: 'block',
                    height: '100%',
                    width: `${pct}%`,
                    borderRadius: 'inherit',
                    background: 'linear-gradient(90deg, #bfd5c1, #dfe7bf)',
                  }}
                />
              </div>
              <strong style={{ whiteSpace: 'nowrap' }}>{value}</strong>
            </div>
          ))}
        </section>

        {/* Mood track */}
        <MoodTrack />
      </aside>
    </div>
  );
}
