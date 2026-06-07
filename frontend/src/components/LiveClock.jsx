import { useEffect, useState } from 'react';

export default function LiveClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const hhmm = now.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  const ss = now.getSeconds().toString().padStart(2, '0');
  const dateStr = now.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });

  return (
    <div style={{ padding: '16px 14px 10px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: '3px',
          lineHeight: 1,
        }}
      >
        <span
          style={{
            fontSize: '34px',
            fontWeight: 700,
            letterSpacing: '-0.06em',
            color: 'var(--text)',
          }}
        >
          {hhmm}
        </span>
        <span
          style={{
            fontSize: '15px',
            fontWeight: 500,
            color: 'var(--muted)',
            letterSpacing: '-0.02em',
          }}
        >
          {ss}
        </span>
      </div>
      <div
        style={{
          fontSize: '11px',
          color: 'var(--muted)',
          marginTop: '5px',
          letterSpacing: '0.01em',
        }}
      >
        {dateStr}
      </div>
    </div>
  );
}
