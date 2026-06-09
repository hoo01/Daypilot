import { useEffect, useRef, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { api } from '../utils/api';
import { storage } from '../utils/storage';
import { getDailyQuote } from '../utils/quotes';
import MoodTrack from '../components/MoodTrack';
import Toast from '../components/Toast';
import LiveClock from '../components/LiveClock';

const HOUR_HEIGHT = 96;
const START_HOUR  = 6;
const END_HOUR    = 26;

const TYPE_META = {
  deep_work: {
    textColor:  '#ffffff',
    mutedColor: 'rgba(255,255,255,0.68)',
    bg:         'linear-gradient(160deg, rgba(78,115,255,0.94), rgba(50,80,220,0.90))',
    border:     'none',
    onDark:     true,
    dot:        '#a5b4fc',
  },
  routine: {
    textColor:  '#e2e8f0',
    mutedColor: 'rgba(226,232,240,0.52)',
    bg:         'linear-gradient(160deg, rgba(100,116,139,0.82), rgba(71,85,105,0.80))',
    border:     'none',
    onDark:     true,
    dot:        '#94a3b8',
  },
  break: {
    textColor:  '#1a1000',
    mutedColor: 'rgba(26,16,0,0.52)',
    bg:         'linear-gradient(160deg, rgba(255,192,70,0.95), rgba(240,165,42,0.93))',
    border:     'none',
    onDark:     false,
    dot:        '#451a03',
  },
  workout: {
    textColor:  '#ffffff',
    mutedColor: 'rgba(255,255,255,0.68)',
    bg:         'linear-gradient(160deg, rgba(251,96,112,0.92), rgba(220,55,78,0.90))',
    border:     'none',
    onDark:     true,
    dot:        '#fecdd3',
  },
  geo: {
    textColor:  '#ffffff',
    mutedColor: 'rgba(255,255,255,0.68)',
    bg:         'linear-gradient(160deg, rgba(155,108,255,0.92), rgba(124,72,235,0.90))',
    border:     'none',
    onDark:     true,
    dot:        '#e9d5ff',
  },
};
const DEFAULT_META = TYPE_META.routine;

const TAG_CHIP = {
  deep_work: { bg: 'rgba(78,115,255,0.88)',  color: '#dde5ff', label: 'Deep Work' },
  routine:   { bg: 'rgba(100,116,138,0.82)', color: '#eef0f4', label: 'Routine'   },
  break:     { bg: 'rgba(213,152,10,0.90)',  color: '#1a1000', label: 'Break'     },
  workout:   { bg: 'rgba(232,64,88,0.88)',   color: '#ffe0e4', label: 'Workout'   },
  geo:       { bg: 'rgba(124,72,235,0.88)',  color: '#ede8ff', label: 'Geo'       },
};

const MOCK_TASKS = [
  { task_id: 'mock_1', title: 'Morning reset & plan review', start_time: todayAt('07:50'), end_time: todayAt('08:30'), type: 'routine',   notes: 'Quiet start with health-aware pacing.' },
  { task_id: 'mock_2', title: 'Deep work block',              start_time: todayAt('09:30'), end_time: todayAt('11:00'), type: 'deep_work', notes: 'Single-focus window for priority work.' },
  { task_id: 'mock_3', title: 'Gym session',                  start_time: todayAt('11:15'), end_time: todayAt('12:30'), type: 'workout',   notes: 'USC Viterbi → LA Fitness Downtown · 18 min drive', geo_segment: { origin: 'USC Viterbi', destination: 'LA Fitness Downtown', duration_text: '18 min drive', maps_url: 'https://www.google.com/maps' } },
  { task_id: 'mock_4', title: 'Lunch and light walk',         start_time: todayAt('13:30'), end_time: todayAt('14:30'), type: 'break',     notes: 'Recovery window before afternoon work.' },
  { task_id: 'mock_5', title: 'Follow-up & responses',        start_time: todayAt('15:00'), end_time: todayAt('16:00'), type: 'routine',   notes: 'Short admin batch with low-friction tasks.' },
  { task_id: 'mock_6', title: 'Planning check-in',            start_time: todayAt('17:20'), end_time: todayAt('17:50'), type: 'routine',   notes: 'Let DayPilot decide if anything should move.' },
  { task_id: 'mock_7', title: 'Recovery & wind-down',         start_time: todayAt('19:00'), end_time: todayAt('20:30'), type: 'break',     notes: "Keep evening light to protect tomorrow's energy." },
];

function todayAt(hhmm) {
  return new Date().toISOString().slice(0, 10) + 'T' + hhmm + ':00';
}
function todayISO() {
  return new Date().toISOString().slice(0, 10);
}
function fmtHour(h) {
  return String(h).padStart(2, '0') + ':00';
}
function toMinutes(isoString) {
  if (!isoString) return null;
  const d = new Date(isoString);
  if (isNaN(d)) return null;
  return d.getHours() * 60 + d.getMinutes();
}
function fmtTime(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  if (isNaN(d)) return '';
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function Panel({ style, children }) {
  return (
    <div
      style={{
        borderRadius: 'var(--radius-xl)',
        background: 'rgba(255,255,255,0.05)',
        backdropFilter: 'var(--glass)',
        boxShadow: 'var(--shadow-soft)',
        overflow: 'hidden',
        position: 'relative',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function Card({ style, children }) {
  return (
    <div
      style={{
        borderRadius: 'var(--radius-lg)',
        background: 'rgba(255,255,255,0.09)',
        overflow: 'hidden',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

const GEO_EXPANDED_HEIGHT = 88;

function TimelineBlock({ task, done, onToggle, aiGenerated, expanded, onToggleExpand, topOffset = 0 }) {
  const meta = TYPE_META[task.type] ?? DEFAULT_META;

  const startMin = toMinutes(task.start_time || task.scheduled_time);
  const endMin   = toMinutes(task.end_time);

  if (startMin === null) return null;

  const offsetMin = startMin - START_HOUR * 60;
  if (offsetMin < 0 || offsetMin >= (END_HOUR - START_HOUR) * 60) return null;

  const durationMin = endMin ? Math.max(endMin - startMin, 20) : 40;
  const top         = offsetMin * (HOUR_HEIGHT / 60) + 3 + topOffset;
  const baseHeight  = Math.max(durationMin * (HOUR_HEIGHT / 60) - 6, 28);
  const height      = baseHeight + (expanded ? GEO_EXPANDED_HEIGHT : 0);
  const hasGeo      = Boolean(task.geo_segment);

  return (
    <div
      className="timeline-block"
      style={{
        position: 'absolute',
        left: '58px',
        right: '10px',
        top: `${top}px`,
        height: `${height}px`,
        borderRadius: '12px',
        background: done ? 'rgba(255,255,255,0.06)' : meta.bg,
        border: 'none',
        display: 'flex',
        flexDirection: 'column',
        cursor: hasGeo ? 'pointer' : 'default',
        opacity: done ? 0.45 : 1,
        zIndex: 2,
        overflow: 'hidden',
        boxShadow: done ? 'none' : '0 4px 20px rgba(0,0,0,0.28)',
      }}
      onClick={() => hasGeo && onToggleExpand?.()}
    >
      {/* task row */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '0 12px',
        height: `${baseHeight}px`,
        flexShrink: 0,
        overflow: 'hidden',
      }}>
        {/* checkbox */}
        <button
          onClick={(e) => { e.stopPropagation(); onToggle?.(); }}
          aria-label={done ? 'Mark incomplete' : 'Mark complete'}
          style={{
            flexShrink: 0,
            width: '18px',
            height: '18px',
            borderRadius: '5px',
            border: done
              ? 'none'
              : `2px solid ${meta.onDark ? 'rgba(255,255,255,0.42)' : 'rgba(0,0,0,0.28)'}`,
            background: done
              ? (meta.onDark ? 'rgba(255,255,255,0.70)' : 'rgba(0,0,0,0.45)')
              : 'transparent',
            color: done
              ? (meta.onDark ? '#4e73ff' : '#fff')
              : 'transparent',
            display: 'grid',
            placeItems: 'center',
            fontSize: '11px',
            fontWeight: 700,
            cursor: 'pointer',
            transition: '120ms ease',
          }}
        >
          {done ? '✓' : ''}
        </button>

        {/* title */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <span
            style={{
              fontSize: baseHeight < 38 ? '12px' : '13px',
              fontWeight: 650,
              letterSpacing: '-0.02em',
              color: done ? meta.mutedColor : meta.textColor,
              textDecoration: done ? 'line-through' : 'none',
              display: 'block',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {task.title}
            {aiGenerated && (
              <span style={{ fontSize: '9px', marginLeft: '5px', opacity: 0.65 }}>◆</span>
            )}
          </span>
          {baseHeight >= 46 && task.notes && (
            <span
              style={{
                fontSize: '11px',
                color: meta.mutedColor,
                display: 'block',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                marginTop: '2px',
              }}
            >
              {task.notes}
            </span>
          )}
        </div>

        {/* time pill */}
        {baseHeight >= 36 && (
          <div
            style={{
              flexShrink: 0,
              fontSize: '10px',
              fontWeight: 600,
              color: meta.mutedColor,
              whiteSpace: 'nowrap',
              fontVariantNumeric: 'tabular-nums',
              background: meta.onDark ? 'rgba(0,0,0,0.20)' : 'rgba(255,255,255,0.28)',
              padding: '3px 8px',
              borderRadius: '999px',
            }}
          >
            {fmtTime(task.start_time || task.scheduled_time)}
            {task.end_time ? ` – ${fmtTime(task.end_time)}` : ''}
          </div>
        )}
      </div>

      {/* geo section — inline inside the block */}
      {hasGeo && expanded && (
        <div onClick={(e) => e.stopPropagation()} style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div style={{
            height: '1px',
            background: meta.onDark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.10)',
            margin: '0 12px',
          }} />
          <div style={{
            flex: 1,
            display: 'grid',
            gridTemplateColumns: '1fr auto',
            gap: '12px',
            padding: '10px 12px 12px',
            alignItems: 'center',
          }}>
            <div>
              <div style={{
                fontSize: '12px',
                fontWeight: 650,
                color: meta.textColor,
                letterSpacing: '-0.02em',
                marginBottom: '3px',
              }}>
                {task.geo_segment.origin} → {task.geo_segment.destination}
              </div>
              <div style={{ fontSize: '11px', color: meta.mutedColor, marginBottom: '8px' }}>
                Est. {task.geo_segment.duration_text}
              </div>
              <div style={{ display: 'flex', gap: '5px' }}>
                <span style={{
                  fontSize: '10px',
                  fontWeight: 600,
                  padding: '2px 7px',
                  borderRadius: '5px',
                  background: meta.onDark ? 'rgba(255,255,255,0.16)' : 'rgba(0,0,0,0.08)',
                  color: meta.onDark ? 'rgba(255,255,255,0.80)' : 'rgba(0,0,0,0.60)',
                  letterSpacing: '0.02em',
                }}>Maps ready</span>
                <span style={{
                  fontSize: '10px',
                  fontWeight: 600,
                  padding: '2px 7px',
                  borderRadius: '5px',
                  background: meta.onDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.05)',
                  color: meta.onDark ? 'rgba(255,255,255,0.48)' : 'rgba(0,0,0,0.40)',
                  letterSpacing: '0.02em',
                }}>Travel-aware</span>
              </div>
            </div>
            <button
              className="geo-navigate-btn"
              onClick={() => window.open(task.geo_segment.maps_url, '_blank', 'noreferrer')}
              style={{
                border: `1px solid ${meta.onDark ? 'rgba(255,255,255,0.28)' : 'rgba(0,0,0,0.15)'}`,
                borderRadius: '10px',
                padding: '7px 13px',
                fontSize: '12px',
                fontWeight: 650,
                color: meta.textColor,
                background: meta.onDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.08)',
                cursor: 'pointer',
                flexShrink: 0,
                whiteSpace: 'nowrap',
                letterSpacing: '-0.01em',
                transition: 'filter 160ms ease',
              }}
            >
              Navigate ↗
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function TodayPage() {
  const navigate      = useNavigate();
  const { openAgentDrawer } = useOutletContext();
  const { tasks, setTasks } = useStore();
  const [doneMap, setDoneMap]         = useState({});
  const [submitting, setSubmitting]   = useState(false);
  const [toast, setToast]             = useState(null);
  const [loading, setLoading]         = useState(true);
  const [noSchedule, setNoSchedule]   = useState(false);
  const [nowMin, setNowMin]           = useState(() => {
    const n = new Date(); return n.getHours() * 60 + n.getMinutes();
  });
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [expandedGeoTaskId, setExpandedGeoTaskId] = useState(null);

  const timelineRef = useRef(null);
  const [quote]     = useState(getDailyQuote);

  const lastFeedbackDate = storage.getLastFeedbackDate();
  const feedbackDone     = lastFeedbackDate === todayISO();

  useEffect(() => {
    const t = setInterval(() => {
      const n = new Date(); setNowMin(n.getHours() * 60 + n.getMinutes());
    }, 60_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const userId = storage.getUserId();
    async function load() {
      try {
        const cached = storage.getTodaySchedule();
        if (cached) { setTasks(cached); setLoading(false); }
        const res    = await api.getScheduleToday(userId);
        const list   = Array.isArray(res) ? res : res.tasks || [];
        const sorted = list.sort((a, b) => (a.start_time || '').localeCompare(b.start_time || ''));
        setTasks(sorted);
        storage.setTodaySchedule(sorted);
        setNoSchedule(false);
      } catch (err) {
        if (err?.status === 404) {
          setNoSchedule(true);
          storage.setTodaySchedule(null);
        } else if (!tasks.length) {
          setTasks(MOCK_TASKS);
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const uid    = params.get('user_id');
    if (uid) { storage.setUserId(uid); navigate('/today', { replace: true }); }
  }, []);

  useEffect(() => {
    if (!timelineRef.current) return;
    timelineRef.current.scrollTop = 0;
  }, [loading]);

  function toggleDone(taskId) {
    setDoneMap((prev) => ({ ...prev, [taskId]: !prev[taskId] }));
  }

  async function handleSubmitFeedback() {
    if (feedbackDone || submitting) return;
    const userId      = storage.getUserId();
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

  const displayTasks = tasks.length ? tasks : [];
  const nowLineTop   = (nowMin - START_HOUR * 60) * (HOUR_HEIGHT / 60);
  const hours        = Array.from({ length: END_HOUR - START_HOUR }, (_, i) => START_HOUR + i);

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `minmax(0,1fr) ${sidebarOpen ? '228px' : '34px'}`,
        gridTemplateRows: '1fr',
        gap: '12px',
        height: '100%',
        minWidth: 0,
        transition: 'grid-template-columns 240ms ease',
      }}
    >
      {/* center panel */}
      <Panel>
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>

          {/* header */}
          <div style={{ padding: '20px 20px 0', flexShrink: 0 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'baseline',
                justifyContent: 'space-between',
                marginBottom: '4px',
              }}
            >
              <h1 style={{ fontSize: '22px', fontWeight: 700, letterSpacing: '-0.04em', margin: 0, color: '#fff' }}>
                Today's Schedule
              </h1>
              <span style={{ fontSize: '11px', color: 'var(--muted)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                {new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date())}
              </span>
            </div>
            <p style={{ fontSize: '13px', color: 'var(--muted)', fontStyle: 'italic', margin: '0 0 14px', lineHeight: 1.55 }}>
              {quote}
            </p>

            {/* legend chips */}
            <div
              style={{
                display: 'flex',
                gap: '6px',
                flexWrap: 'wrap',
                paddingBottom: '14px',
              }}
            >
              {Object.entries(TAG_CHIP).map(([key, { bg, color, label }]) => (
                <div
                  key={key}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    padding: '3px 9px',
                    borderRadius: '6px',
                    background: bg,
                    color,
                    fontSize: '11px',
                    fontWeight: 600,
                    letterSpacing: '0.02em',
                  }}
                >
                  {label}
                </div>
              ))}
            </div>
          </div>

          {/* timeline */}
          <div
            ref={timelineRef}
            style={{ flex: 1, minHeight: 0, overflowY: 'auto', position: 'relative', padding: '0 0 24px' }}
          >
            {loading ? (
              <div style={{ padding: '40px 20px', color: 'var(--muted)', fontSize: '13px', textAlign: 'center' }}>
                Loading schedule...
              </div>
            ) : noSchedule ? (
              <div style={{ padding: '60px 20px', textAlign: 'center' }}>
                <div style={{ fontSize: '32px', marginBottom: '12px', opacity: 0.35 }}>◆</div>
                <p style={{ fontSize: '15px', fontWeight: 600, color: '#fff', marginBottom: '8px' }}>
                  No schedule yet
                </p>
                <p style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.6, margin: '0 0 20px' }}>
                  Chat with DayPilot to build your day plan.
                </p>
                <button
                  onClick={openAgentDrawer}
                  style={{
                    padding: '10px 24px',
                    borderRadius: '14px',
                    border: '1px solid rgba(110,231,183,0.35)',
                    background: 'rgba(110,231,183,0.12)',
                    color: 'var(--accent)',
                    fontSize: '13px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Plan my day ◆
                </button>
              </div>
            ) : (
              <div style={{ position: 'relative', height: `${(END_HOUR - START_HOUR) * HOUR_HEIGHT}px` }}>
                {/* hour labels — no grid lines */}
                {hours.map((h) => (
                  <div
                    key={h}
                    style={{
                      position: 'absolute',
                      top: `${(h - START_HOUR) * HOUR_HEIGHT}px`,
                      left: 0,
                      width: '52px',
                      height: `${HOUR_HEIGHT}px`,
                      display: 'flex',
                      alignItems: 'flex-start',
                      paddingTop: '2px',
                    }}
                  >
                    <div style={{
                      paddingLeft: '14px',
                      fontSize: '13px',
                      fontWeight: 700,
                      color: 'rgba(255,255,255,0.36)',
                      fontVariantNumeric: 'tabular-nums',
                      userSelect: 'none',
                      letterSpacing: '0.01em',
                    }}>
                      {fmtHour(h)}
                    </div>
                  </div>
                ))}

                {/* now line */}
                {nowMin >= START_HOUR * 60 && nowMin < END_HOUR * 60 && (
                  <div
                    style={{
                      position: 'absolute',
                      left: '50px', right: '10px',
                      top: `${nowLineTop}px`,
                      height: '2px',
                      background: 'linear-gradient(90deg, var(--error), rgba(248,113,113,0))',
                      borderRadius: '999px',
                      zIndex: 3,
                      animation: 'now-line-pulse 3s ease-in-out infinite',
                      pointerEvents: 'none',
                    }}
                  >
                    <span style={{ position: 'absolute', left: '-4px', top: '-3px', width: '8px', height: '8px', borderRadius: '50%', background: 'var(--error)' }} />
                  </div>
                )}

                {/* tasks */}
                {(() => {
                  const expandedTask = expandedGeoTaskId
                    ? displayTasks.find(t => t.task_id === expandedGeoTaskId) ?? null
                    : null;
                  const expandedStartMin = expandedTask
                    ? (toMinutes(expandedTask.start_time || expandedTask.scheduled_time) ?? -Infinity)
                    : -Infinity;
                  return displayTasks.map((task) => {
                    const thisMin = toMinutes(task.start_time || task.scheduled_time) ?? 0;
                    const topOffset = (expandedTask && task.task_id !== expandedGeoTaskId && thisMin > expandedStartMin)
                      ? GEO_EXPANDED_HEIGHT : 0;
                    return (
                      <TimelineBlock
                        key={task.task_id}
                        task={task}
                        done={Boolean(doneMap[task.task_id])}
                        onToggle={() => toggleDone(task.task_id)}
                        aiGenerated
                        expanded={task.task_id === expandedGeoTaskId}
                        onToggleExpand={() => setExpandedGeoTaskId(prev => prev === task.task_id ? null : task.task_id)}
                        topOffset={topOffset}
                      />
                    );
                  });
                })()}
              </div>
            )}
          </div>

          {/* bottom bar */}
          <div
            style={{
              padding: '12px 16px 16px',
              background: 'rgba(5,3,20,0.55)',
              backdropFilter: 'blur(20px)',
              flexShrink: 0,
            }}
          >
            <div
              onClick={openAgentDrawer}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && openAgentDrawer()}
              style={{
                borderRadius: '20px',
                border: '1px solid rgba(255,255,255,0.18)',
                background: 'rgba(255,255,255,0.07)',
                backdropFilter: 'blur(20px) saturate(180%)',
                padding: '10px 10px 10px 16px',
                display: 'flex', alignItems: 'center', gap: '10px',
                cursor: 'text', marginBottom: '10px',
              }}
            >
              <span style={{ fontSize: '13px', color: 'var(--accent)', flexShrink: 0 }}>◆</span>
              <input
                className="compose-input"
                placeholder="Ask DayPilot to reschedule, add, or explain..."
                readOnly
                style={{
                  flex: 1, border: 0, outline: 'none',
                  background: 'transparent', color: 'var(--muted)',
                  fontSize: '13px', letterSpacing: '0.01em', cursor: 'text',
                }}
              />
              <button
                type="button"
                className="send-btn"
                onClick={(e) => { e.stopPropagation(); openAgentDrawer(); }}
                style={{
                  width: '38px', height: '38px', borderRadius: '14px',
                  border: '1px solid rgba(110,231,183,0.28)',
                  background: 'rgba(110,231,183,0.14)',
                  color: 'var(--accent)', cursor: 'pointer',
                  display: 'grid', placeItems: 'center', fontSize: '15px', flexShrink: 0,
                }}
              >
                ↑
              </button>
            </div>

            <button
              className="submit-btn"
              onClick={handleSubmitFeedback}
              disabled={feedbackDone || submitting}
              style={{
                width: '100%',
                padding: '12px',
                borderRadius: '16px',
                border: 'none',
                background: feedbackDone
                  ? 'rgba(255,255,255,0.07)'
                  : 'linear-gradient(135deg, rgba(16,185,129,0.90) 0%, rgba(99,102,241,0.80) 100%)',
                color: feedbackDone ? 'var(--muted)' : '#ffffff',
                fontSize: '13px',
                fontWeight: 700,
                letterSpacing: '0.02em',
                cursor: feedbackDone || submitting ? 'not-allowed' : 'pointer',
                opacity: submitting ? 0.65 : 1,
              }}
            >
              {feedbackDone ? '✓ Progress submitted for today' : submitting ? 'Submitting…' : "Submit today's progress"}
            </button>
          </div>

          {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
        </div>
      </Panel>

      {/* right sidebar */}
      {sidebarOpen ? (
        <Panel>
          {/* collapse toggle — absolute top-left, flush with panel edge */}
          <button
            onClick={() => setSidebarOpen(false)}
            title="Collapse sidebar"
            style={{
              position: 'absolute',
              top: '10px',
              left: '10px',
              zIndex: 10,
              width: '26px',
              height: '26px',
              borderRadius: '9px',
              border: 'none',
              background: 'rgba(255,255,255,0.10)',
              color: 'var(--muted)',
              cursor: 'pointer',
              display: 'grid',
              placeItems: 'center',
              fontSize: '16px',
              transition: '160ms ease',
            }}
          >
            ›
          </button>

          <div style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            padding: '10px',
            paddingTop: '44px',
            gap: '8px',
          }}>

            {/* clock */}
            <Card style={{ flexShrink: 0 }}>
              <LiveClock />
            </Card>

            {/* at a glance */}
            <Card style={{ flexShrink: 0 }}>
              <div style={{ padding: '11px 13px 12px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--muted-2)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '10px' }}>
                  Today at a glance
                </div>
                {[
                  { label: 'Commute risk', pct: 28, value: 'Low'    },
                  { label: 'Focus window', pct: 78, value: 'Strong' },
                  { label: 'Task density', pct: 62, value: 'Medium' },
                ].map(({ label, pct, value }) => (
                  <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '7px', fontSize: '11px', marginBottom: '8px' }}>
                    <span style={{ whiteSpace: 'nowrap', width: '76px', flexShrink: 0, color: 'var(--muted)' }}>{label}</span>
                    <div style={{ flex: 1, height: '5px', borderRadius: '999px', background: 'rgba(255,255,255,0.10)', overflow: 'hidden' }}>
                      <span style={{ display: 'block', height: '100%', width: `${pct}%`, borderRadius: 'inherit', background: 'linear-gradient(90deg, var(--accent-3), var(--accent-2))' }} />
                    </div>
                    <strong style={{ whiteSpace: 'nowrap', width: '40px', textAlign: 'right', fontWeight: 600, color: '#fff', fontSize: '10px', fontVariantNumeric: 'tabular-nums' }}>{value}</strong>
                  </div>
                ))}
              </div>
            </Card>

            {/* health */}
            <Card style={{ flexShrink: 0 }}>
              <div style={{ padding: '11px 11px 10px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--muted-2)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '9px' }}>
                  Health
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '7px' }}>
                  {[
                    { label: 'Heart Rate', value: '68',    unit: 'BPM',     accent: '#f87171' },
                    { label: 'Hydration',  value: '5 / 8', unit: 'GLASSES', accent: '#60a5fa' },
                    { label: 'Sleep',      value: '7.5',   unit: 'HRS',     accent: '#a78bfa' },
                    { label: 'Steps',      value: '4,230', unit: 'TODAY',   accent: 'var(--accent-3)' },
                  ].map(({ label, value, unit, accent }) => (
                    <div
                      key={label}
                      style={{
                        padding: '9px 10px 8px',
                        borderRadius: '12px',
                        background: 'rgba(255,255,255,0.10)',
                      }}
                    >
                      <div style={{ fontSize: '9px', fontWeight: 700, letterSpacing: '0.07em', color: 'var(--muted-2)', textTransform: 'uppercase', marginBottom: '5px' }}>
                        {label}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: '3px' }}>
                        <span style={{ fontSize: '20px', fontWeight: 700, letterSpacing: '-0.04em', color: accent, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
                          {value}
                        </span>
                        <span style={{ fontSize: '9px', fontWeight: 600, color: 'var(--muted-2)', letterSpacing: '0.04em' }}>
                          {unit}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </Card>

            {/* mood — fills remaining sidebar height */}
            <div style={{ flex: 1, minHeight: 0 }}>
              <MoodTrack style={{ height: '100%' }} />
            </div>

          </div>
        </Panel>
      ) : (
        <Panel>
          <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: '12px' }}>
            <button
              onClick={() => setSidebarOpen(true)}
              title="Expand sidebar"
              style={{
                width: '26px', height: '26px',
                borderRadius: '9px',
                border: 'none',
                background: 'rgba(255,255,255,0.09)',
                color: 'var(--muted)', cursor: 'pointer',
                display: 'grid', placeItems: 'center', fontSize: '14px',
                transition: '160ms ease',
              }}
            >
              ‹
            </button>
          </div>
        </Panel>
      )}
    </div>
  );
}
