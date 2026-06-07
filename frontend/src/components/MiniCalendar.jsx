import { useMemo } from 'react';
import { useStore } from '../store/useStore';

const DAY_HEADERS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

export default function MiniCalendar() {
  const tasks = useStore((s) => s.tasks);
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth();

  const taskDays = useMemo(() => {
    const days = new Set();
    tasks.forEach((t) => {
      const raw = t.start_time || t.scheduled_time;
      if (!raw) return;
      const d = new Date(raw);
      if (d.getFullYear() === year && d.getMonth() === month) days.add(d.getDate());
    });
    return days;
  }, [tasks, year, month]);

  const monthLabel = today.toLocaleString('en-US', { month: 'long', year: 'numeric' });
  const firstDow = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const todayDate = today.getDate();

  const cells = [];
  for (let i = 0; i < firstDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  return (
    <div style={{ padding: '14px 12px 12px' }}>
      <div
        style={{
          fontSize: '12px',
          fontWeight: 700,
          letterSpacing: '-0.03em',
          color: 'var(--text)',
          marginBottom: '10px',
        }}
      >
        {monthLabel}
      </div>

      {/* day-of-week headers */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', marginBottom: '3px' }}>
        {DAY_HEADERS.map((d, i) => (
          <div
            key={i}
            style={{
              textAlign: 'center',
              fontSize: '10px',
              fontWeight: 600,
              color: 'var(--muted)',
              padding: '2px 0',
            }}
          >
            {d}
          </div>
        ))}
      </div>

      {/* date cells */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '1px' }}>
        {cells.map((d, i) => {
          const isToday = d === todayDate;
          const hasTasks = d && taskDays.has(d) && !isToday;
          return (
            <div
              key={i}
              style={{
                position: 'relative',
                textAlign: 'center',
                fontSize: '11px',
                padding: '5px 1px',
                borderRadius: '7px',
                fontWeight: isToday ? 700 : 400,
                background: isToday
                  ? 'linear-gradient(135deg, #161d1b, #36423c)'
                  : 'transparent',
                color: isToday ? 'white' : d ? 'var(--text)' : 'transparent',
              }}
            >
              {d ?? ''}
              {hasTasks && (
                <span
                  style={{
                    position: 'absolute',
                    bottom: '2px',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: '3px',
                    height: '3px',
                    borderRadius: '50%',
                    background: 'var(--accent-4)',
                    display: 'block',
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
