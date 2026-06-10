import { useEffect, useRef, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { api } from '../utils/api';
import { storage } from '../utils/storage';
import { getDailyQuote } from '../utils/quotes';
import MapCommute from '../components/MapCommute';
import Toast from '../components/Toast';
import LiveClock from '../components/LiveClock';

const HOUR_HEIGHT = 96;
const START_HOUR  = 6;
const END_HOUR    = 26;

const TYPE_META = {
  deep_work: {
    textColor:  '#ffffff',
    mutedColor: 'rgba(255,255,255,0.68)',
    bg:         'linear-gradient(160deg, rgba(78,115,255,0.78), rgba(50,80,220,0.72))',
    border:     '1px solid rgba(130,160,255,0.24)',
    onDark:     true,
    dot:        '#a5b4fc',
  },
  routine: {
    textColor:  '#c8d8f0',
    mutedColor: 'rgba(200,216,240,0.52)',
    bg:         'linear-gradient(160deg, rgba(36,50,80,0.82), rgba(24,36,66,0.78))',
    border:     '1px solid rgba(255,255,255,0.09)',
    onDark:     true,
    dot:        '#6e86b4',
  },
  break: {
    textColor:  '#1a1000',
    mutedColor: 'rgba(26,16,0,0.52)',
    bg:         'linear-gradient(160deg, rgba(255,192,70,0.88), rgba(240,165,42,0.84))',
    border:     '1px solid rgba(255,200,90,0.28)',
    onDark:     false,
    dot:        '#451a03',
  },
  workout: {
    textColor:  '#ffffff',
    mutedColor: 'rgba(255,255,255,0.68)',
    bg:         'linear-gradient(160deg, rgba(251,96,112,0.82), rgba(220,55,78,0.78))',
    border:     '1px solid rgba(255,130,140,0.24)',
    onDark:     true,
    dot:        '#fecdd3',
  },
  geo: {
    textColor:  '#ffffff',
    mutedColor: 'rgba(255,255,255,0.68)',
    bg:         'linear-gradient(160deg, rgba(155,108,255,0.82), rgba(124,72,235,0.78))',
    border:     '1px solid rgba(185,145,255,0.24)',
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

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function fmtHour(h) {
  return String(h % 24).padStart(2, '0') + ':00';
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
      className="floating-panel"
      style={{
        borderRadius: 'var(--radius-xl)',
        overflow: 'hidden',
        position: 'relative',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function Card({ style, className, children }) {
  return (
    <div
      className={className}
      style={{
        borderRadius: 'var(--radius-lg)',
        background: 'rgba(255,255,255,0.05)',
        overflow: 'hidden',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

const GEO_EXPANDED_HEIGHT = 88;

function assignColumns(tasks) {
  const assignments = new Map();
  const valid = tasks.filter(t => toMinutes(t.start_time || t.scheduled_time) !== null);
  const sorted = [...valid].sort((a, b) =>
    (toMinutes(a.start_time || a.scheduled_time) ?? 0) - (toMinutes(b.start_time || b.scheduled_time) ?? 0)
  );
  const colEnds = [];
  for (const task of sorted) {
    const s = toMinutes(task.start_time || task.scheduled_time) ?? 0;
    const e = toMinutes(task.end_time) ?? (s + 40);
    let col = colEnds.findIndex(end => end <= s);
    if (col === -1) col = colEnds.length;
    colEnds[col] = e;
    assignments.set(task.task_id, { col, totalCols: 1 });
  }
  for (const task of sorted) {
    const s = toMinutes(task.start_time || task.scheduled_time) ?? 0;
    const e = toMinutes(task.end_time) ?? (s + 40);
    let maxCol = assignments.get(task.task_id)?.col ?? 0;
    for (const other of sorted) {
      if (other.task_id === task.task_id) continue;
      const os = toMinutes(other.start_time || other.scheduled_time) ?? 0;
      const oe = toMinutes(other.end_time) ?? (os + 40);
      if (os < e && oe > s) maxCol = Math.max(maxCol, assignments.get(other.task_id)?.col ?? 0);
    }
    const info = assignments.get(task.task_id);
    if (info) info.totalCols = maxCol + 1;
  }
  return assignments;
}

function TimelineBlock({ task, done, onToggle, aiGenerated, expanded, onToggleExpand, topOffset = 0, col = 0, totalCols = 1 }) {
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

  const GAP = 3;
  const totalGap = (totalCols - 1) * GAP;
  const colBase = `(100% - ${68 + totalGap}px) / ${totalCols}`;
  const blockLeft = totalCols <= 1 || col === 0
    ? '58px'
    : `calc(58px + ${col} * (${colBase} + ${GAP}px))`;
  const blockRight = totalCols <= 1 || col === totalCols - 1
    ? '10px'
    : `calc(10px + ${totalCols - 1 - col} * (${colBase} + ${GAP}px))`;

  return (
    <div
      className="timeline-block"
      style={{
        position: 'absolute',
        left: blockLeft,
        right: blockRight,
        top: `${top}px`,
        height: `${height}px`,
        borderRadius: '12px',
        background: done ? 'rgba(255,255,255,0.04)' : meta.bg,
        border: done ? '1px solid rgba(255,255,255,0.07)' : meta.border,
        backdropFilter: 'blur(8px) saturate(130%)',
        WebkitBackdropFilter: 'blur(8px) saturate(130%)',
        display: 'flex',
        flexDirection: 'column',
        cursor: hasGeo ? 'pointer' : 'default',
        opacity: done ? 0.42 : 1,
        zIndex: 2,
        overflow: 'hidden',
        boxShadow: done ? 'none' : '0 4px 22px rgba(0,0,0,0.26), inset 0 1px 0 rgba(255,255,255,0.12)',
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
  const { tasks, noSchedule, refreshSchedule } = useStore();
  const [doneMap, setDoneMap]         = useState({});
  const [submitting, setSubmitting]   = useState(false);
  const [toast, setToast]             = useState(null);
  const [loading, setLoading]         = useState(true);
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
    const cached = storage.getTodaySchedule();
    if (cached) { useStore.setState({ tasks: cached }); setLoading(false); }
    refreshSchedule(userId).finally(() => setLoading(false));
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
      storage.setTodaySchedule(null);
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
              <h1 style={{ fontSize: '22px', fontWeight: 700, letterSpacing: '0.04em', margin: 0, color: '#fff' }}>
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
            ) : feedbackDone ? (
              <div style={{ padding: '60px 20px', textAlign: 'center' }}>
                <div style={{ fontSize: '32px', marginBottom: '12px', opacity: 0.55 }}>✓</div>
                <p style={{ fontSize: '15px', fontWeight: 600, color: '#fff', marginBottom: '8px' }}>
                  Day complete
                </p>
                <p style={{ fontSize: '13px', color: 'var(--muted)', lineHeight: 1.6, margin: '0 0 20px' }}>
                  Great work today. Chat with DayPilot to plan tomorrow.
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
                  Plan tomorrow ◆
                </button>
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
                  const colAssignments = assignColumns(displayTasks);
                  return displayTasks.map((task) => {
                    const thisMin = toMinutes(task.start_time || task.scheduled_time) ?? 0;
                    const topOffset = (expandedTask && task.task_id !== expandedGeoTaskId && thisMin > expandedStartMin)
                      ? GEO_EXPANDED_HEIGHT : 0;
                    const colInfo = colAssignments.get(task.task_id);
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
                        col={colInfo?.col ?? 0}
                        totalCols={colInfo?.totalCols ?? 1}
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
            <Card className="sidebar-card-in" style={{ flexShrink: 0, animationDelay: '0.05s' }}>
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
            <Card className="sidebar-card-in" style={{ flexShrink: 0, animationDelay: '0.18s' }}>
              <div style={{ padding: '11px 11px 10px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--muted-2)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '9px' }}>
                  Health
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '7px' }}>
                  {[
                    {
                      label: 'Sleep', value: '7.5', unit: 'h', sub: '-0.5h vs avg',
                      accent: '#a78bfa', bg: 'rgba(167,139,250,0.10)', border: 'rgba(167,139,250,0.22)',
                      icon: (
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                          <path d="M3 8a5 5 0 0 0 9.93 1A5.5 5.5 0 0 1 7 3.07 5 5 0 0 0 3 8z" stroke="#a78bfa" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      ),
                    },
                    {
                      label: 'Energy', value: '72', unit: '/100', sub: 'Moderate',
                      accent: '#6ee7b7', bg: 'rgba(110,231,183,0.10)', border: 'rgba(110,231,183,0.28)',
                      icon: (
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                          <circle cx="8" cy="8" r="5.5" stroke="#6ee7b7" strokeWidth="1.3"/>
                          <circle cx="8" cy="8" r="3" stroke="#6ee7b7" strokeWidth="1.3"/>
                          <circle cx="8" cy="8" r="1" fill="#6ee7b7"/>
                        </svg>
                      ),
                    },
                    {
                      label: 'Focus', value: '9PM', unit: '', sub: 'to 1AM · best time',
                      accent: '#60a5fa', bg: 'rgba(96,165,250,0.08)', border: 'rgba(96,165,250,0.20)',
                      icon: (
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                          <path d="M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2z" stroke="#60a5fa" strokeWidth="1.3"/>
                          <path d="M5 8l2 2 4-4" stroke="#60a5fa" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      ),
                    },
                    {
                      label: 'Tasks', value: '3', unit: '/10', sub: 'This week',
                      accent: '#fb923c', bg: 'rgba(251,146,60,0.08)', border: 'rgba(251,146,60,0.20)',
                      icon: (
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                          <circle cx="8" cy="8" r="3" stroke="#fb923c" strokeWidth="1.3"/>
                          <path d="M8 1v2M8 13v2M1 8h2M13 8h2" stroke="#fb923c" strokeWidth="1.3" strokeLinecap="round"/>
                        </svg>
                      ),
                    },
                  ].map(({ label, value, unit, sub, accent, bg, border, icon }) => (
                    <div
                      key={label}
                      className="health-card"
                      style={{
                        padding: '9px 9px 8px',
                        borderRadius: '12px',
                        background: bg,
                        border: `1px solid ${border}`,
                        backdropFilter: 'blur(10px) saturate(150%)',
                        WebkitBackdropFilter: 'blur(10px) saturate(150%)',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '4px' }}>
                        <div style={{ fontSize: '9px', fontWeight: 700, letterSpacing: '0.06em', color: accent, textTransform: 'uppercase' }}>
                          {label}
                        </div>
                        {icon}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: '2px' }}>
                        <span style={{ fontSize: '18px', fontWeight: 700, letterSpacing: '-0.03em', color: '#fff', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
                          {value}
                        </span>
                        {unit && (
                          <span style={{ fontSize: '9px', fontWeight: 600, color: accent, letterSpacing: '0.04em' }}>
                            {unit}
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: '9px', color: 'var(--muted-2)', marginTop: '3px', lineHeight: 1.3 }}>
                        {sub}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </Card>

            {/* map & commute */}
            <div className="sidebar-card-in" style={{ flex: 1, minHeight: 0, animationDelay: '0.31s' }}>
              <MapCommute tasks={displayTasks} style={{ height: '100%' }} />
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
