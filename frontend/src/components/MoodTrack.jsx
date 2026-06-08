import { useState } from 'react';
import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { storage } from '../utils/storage';

const MOODS = [
  { value: 1, label: 'Drained',   icon: '○' },
  { value: 2, label: 'Low',       icon: '◔' },
  { value: 3, label: 'Okay',      icon: '◑' },
  { value: 4, label: 'Calm',      icon: '◕' },
  { value: 5, label: 'Energized', icon: '●' },
];

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

export default function MoodTrack({ style }) {
  const [log, setLog]  = useState(storage.getMoodLog());
  const today          = todayStr();
  const todayEntry     = log.find((e) => e.date === today);
  const selected       = todayEntry?.value ?? null;

  function select(mood) {
    const updated = log.filter((e) => e.date !== today);
    updated.push({ date: today, value: mood.value, label: mood.label, source: 'user_input' });
    storage.setMoodLog(updated);
    setLog(updated);
  }

  const last7        = log.slice(-7).map((e) => ({ v: e.value }));
  const hasSparkline = last7.length >= 2;

  return (
    <section
      style={{
        borderRadius: 'var(--radius-lg)',
        background: 'rgba(255,255,255,0.09)',
        padding: '14px',
        boxSizing: 'border-box',
        ...style,
      }}
    >
      {/* header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          gap: '8px',
          marginBottom: '12px',
        }}
      >
        <div>
          <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 700, letterSpacing: '-0.03em', color: '#fff' }}>
            Mood check
          </h3>
          <p style={{ margin: '3px 0 0', color: 'var(--muted)', fontSize: '11px', lineHeight: 1.4 }}>
            One daily check-in.
          </p>
        </div>
        <div
          style={{
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: 'var(--muted-2)',
            padding: '4px 9px',
            borderRadius: '999px',
            background: 'rgba(255,255,255,0.07)',
            border: '1px solid rgba(255,255,255,0.10)',
            whiteSpace: 'nowrap',
          }}
        >
          Daily
        </div>
      </div>

      {/* mood buttons */}
      <div
        style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '8px', marginBottom: '12px' }}
        aria-label="Mood options"
      >
        {MOODS.map((mood) => {
          const active = selected === mood.value;
          return (
            <button
              key={mood.value}
              title={mood.label}
              onClick={() => select(mood)}
              style={{
                aspectRatio: '1',
                borderRadius: '14px',
                border: active ? '1px solid rgba(110,231,183,0.40)' : '1px solid rgba(255,255,255,0.10)',
                background: active ? 'rgba(110,231,183,0.16)' : 'rgba(255,255,255,0.06)',
                display: 'grid', placeItems: 'center',
                color: active ? 'var(--accent)' : 'var(--muted)',
                fontSize: '18px',
                cursor: 'pointer',
                transition: '160ms ease',
                boxShadow: active ? '0 4px 16px rgba(110,231,183,0.15)' : 'none',
              }}
            >
              {mood.icon}
            </button>
          );
        })}
      </div>

      {/* sparkline */}
      {hasSparkline ? (
        <div
          style={{
            borderRadius: '12px',
            border: '1px solid rgba(255,255,255,0.08)',
            background: 'rgba(255,255,255,0.04)',
            padding: '12px 10px 8px',
          }}
        >
          <ResponsiveContainer width="100%" height={44}>
            <LineChart data={last7}>
              <Line
                type="monotone"
                dataKey="v"
                stroke="var(--accent-3)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p style={{ fontSize: '11px', color: 'var(--muted-2)', fontStyle: 'italic', textAlign: 'center', marginTop: '4px' }}>
          Keep checking in to see your trend.
        </p>
      )}
    </section>
  );
}
