import { useState, useEffect } from 'react';
import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { storage } from '../utils/storage';

const MOODS = [
  { value: 1, label: 'drained',   icon: '○' },
  { value: 2, label: 'low',       icon: '◔' },
  { value: 3, label: 'okay',      icon: '◑' },
  { value: 4, label: 'calm',      icon: '◕' },
  { value: 5, label: 'energized', icon: '●' },
];

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

export default function MoodTrack() {
  const [log, setLog] = useState(storage.getMoodLog());
  const today = todayStr();
  const todayEntry = log.find((e) => e.date === today);
  const selected = todayEntry?.value ?? null;

  function select(mood) {
    const updated = log.filter((e) => e.date !== today);
    updated.push({ date: today, value: mood.value, label: mood.label, source: 'user_input' });
    storage.setMoodLog(updated);
    setLog(updated);
  }

  const last7 = log.slice(-7).map((e) => ({ v: e.value }));
  const hasSparkline = last7.length >= 2;

  return (
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
      {/* header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          gap: '10px',
          marginBottom: '12px',
        }}
      >
        <div>
          <h3
            style={{
              margin: 0,
              fontSize: '18px',
              fontWeight: 700,
              letterSpacing: '-0.05em',
            }}
          >
            Mood check
          </h3>
          <p style={{ margin: '4px 0 0', color: 'var(--muted)', fontSize: '12px', lineHeight: 1.5 }}>
            One daily check-in, shown as a soft green trend.
          </p>
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
            whiteSpace: 'nowrap',
          }}
        >
          Daily
        </div>
      </div>

      {/* mood selectors */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(5, 1fr)',
          gap: '10px',
          marginBottom: '14px',
        }}
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
                borderRadius: '18px',
                border: active ? 'none' : '1px solid rgba(21,29,25,0.06)',
                background: active
                  ? 'linear-gradient(180deg, rgba(211,228,214,0.88), rgba(164,199,170,0.86))'
                  : 'rgba(255,255,255,0.56)',
                display: 'grid',
                placeItems: 'center',
                color: active ? 'white' : '#7d9f87',
                fontSize: '18px',
                boxShadow: active
                  ? '0 12px 24px rgba(21,29,25,0.10)'
                  : 'inset 0 1px 0 rgba(255,255,255,0.45)',
                cursor: 'pointer',
                transition: '160ms ease',
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
            borderRadius: '18px',
            border: '1px solid rgba(21,29,25,0.06)',
            background: 'linear-gradient(180deg, rgba(255,255,255,0.48), rgba(237,242,231,0.68))',
            padding: '14px 12px 10px',
          }}
        >
          <ResponsiveContainer width="100%" height={48}>
            <LineChart data={last7}>
              <Line
                type="monotone"
                dataKey="v"
                stroke="var(--accent-4)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p
          style={{
            fontSize: '12px',
            color: 'var(--muted)',
            fontStyle: 'italic',
            textAlign: 'center',
            marginTop: '4px',
          }}
        >
          Keep checking in to see your trend.
        </p>
      )}
    </section>
  );
}
