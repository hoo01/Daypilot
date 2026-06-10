import { useState } from 'react';

function toMin(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  return d.getHours() * 60 + d.getMinutes();
}

function fmtMin(minutes) {
  const h = Math.floor(((minutes % 1440) + 1440) % 1440 / 60);
  const m = Math.round(minutes % 60);
  const period = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 || 12;
  return `${h12}:${String(m).padStart(2, '0')} ${period}`;
}

function parseDurMin(text) {
  if (!text) return 15;
  const match = text.match(/(\d+)\s*min/);
  return match ? parseInt(match[1]) : 15;
}

export default function MapCommute({ tasks = [], style }) {
  const [locState, setLocState] = useState('idle'); // 'idle' | 'requesting' | 'granted' | 'denied'

  const geoTasks = tasks
    .filter(t => t.geo_segment)
    .sort((a, b) => (toMin(a.start_time) ?? 0) - (toMin(b.start_time) ?? 0));
  const upcoming = geoTasks[0] ?? null;

  const leaveBy = upcoming
    ? fmtMin((toMin(upcoming.start_time) ?? 0) - parseDurMin(upcoming.geo_segment?.duration_text))
    : null;

  function requestLocation() {
    if (!('geolocation' in navigator)) { setLocState('denied'); return; }
    setLocState('requesting');
    navigator.geolocation.getCurrentPosition(
      () => setLocState('granted'),
      () => setLocState('denied'),
    );
  }

  return (
    <div
      className="sidebar-card"
      style={{
        borderRadius: 'var(--radius-lg)',
        background: 'rgba(255,255,255,0.05)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        ...style,
      }}
    >
      <div style={{ padding: '11px 12px 12px', flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', minHeight: 0 }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
          <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--muted-2)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Map & Commute
          </div>

          {locState === 'granted' ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '9px', color: 'var(--accent)', fontWeight: 600 }}>
              <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: 'var(--accent)', display: 'inline-block', animation: 'pulse-dot 2.4s ease-in-out infinite' }}/>
              Live
            </div>
          ) : locState === 'denied' ? (
            <span style={{ fontSize: '9px', color: 'var(--muted-2)' }}>Location off</span>
          ) : (
            <button
              onClick={requestLocation}
              disabled={locState === 'requesting'}
              style={{
                fontSize: '9px', fontWeight: 600,
                padding: '2px 7px', borderRadius: '999px',
                border: '1px solid rgba(96,165,250,0.32)',
                background: 'rgba(96,165,250,0.08)',
                color: '#60a5fa', cursor: 'pointer',
                opacity: locState === 'requesting' ? 0.6 : 1,
                transition: 'opacity 160ms ease',
              }}
            >
              {locState === 'requesting' ? 'Requesting…' : 'Allow location'}
            </button>
          )}
        </div>

        {upcoming ? (
          <>
            {/* Map + route info */}
            <div style={{ display: 'grid', gridTemplateColumns: '94px 1fr', gap: '10px', alignItems: 'center', flexShrink: 0 }}>

              {/* CSS mock map */}
              <div style={{
                height: '74px', borderRadius: '9px',
                background: 'linear-gradient(165deg, #182030 0%, #0c1724 100%)',
                border: '1px solid rgba(255,255,255,0.09)',
                position: 'relative', overflow: 'hidden',
              }}>
                {/* street grid */}
                {[24, 50, 72].map(y => (
                  <div key={y} style={{ position: 'absolute', left: 0, right: 0, top: `${y}%`, height: '1px', background: 'rgba(255,255,255,0.07)' }}/>
                ))}
                {[20, 40, 60, 80, 92].map(x => (
                  <div key={x} style={{ position: 'absolute', top: 0, bottom: 0, left: `${x}%`, width: '1px', background: 'rgba(255,255,255,0.07)' }}/>
                ))}
                {/* main route */}
                <svg style={{ position: 'absolute', inset: 0 }} viewBox="0 0 94 74" fill="none" preserveAspectRatio="none">
                  <path d="M 14 58 L 14 40 L 40 40 L 40 22 L 68 22 L 68 50 L 82 50"
                    stroke="#f59e0b" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                {/* origin pin */}
                <div style={{
                  position: 'absolute', left: '15%', top: '78%',
                  transform: 'translate(-50%,-50%)',
                  width: '8px', height: '8px', borderRadius: '50%',
                  background: '#22c55e', border: '1.5px solid rgba(255,255,255,0.9)',
                  boxShadow: '0 0 7px rgba(34,197,94,0.75)',
                }}/>
                {/* dest pin */}
                <div style={{
                  position: 'absolute', right: '11%', top: '68%',
                  transform: 'translate(50%,-50%)',
                  width: '8px', height: '8px', borderRadius: '50%',
                  background: '#f59e0b', border: '1.5px solid rgba(255,255,255,0.9)',
                  boxShadow: '0 0 7px rgba(245,158,11,0.75)',
                }}/>
              </div>

              {/* Route info */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
                <div style={{ fontSize: '9px', color: 'var(--muted-2)', letterSpacing: '0.04em' }}>Leave by</div>
                <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--accent)', letterSpacing: '-0.03em', lineHeight: 1.1 }}>
                  {leaveBy}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--muted)', marginTop: '3px', lineHeight: 1.35 }}>
                  {upcoming.geo_segment?.duration_text ?? '~15 min'}<br/>
                  <span style={{ color: '#22c55e' }}>Light traffic</span>
                </div>
                <div style={{ fontSize: '9px', color: 'var(--muted-2)', marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {upcoming.geo_segment?.destination}
                </div>
              </div>
            </div>

            {/* Navigate button */}
            <button
              className="choose-plan-btn"
              onClick={() => window.open(upcoming.geo_segment?.maps_url || 'https://maps.google.com', '_blank', 'noreferrer')}
              style={{
                width: '100%', padding: '8px 0',
                borderRadius: '10px',
                border: '1px solid rgba(245,158,11,0.28)',
                background: 'rgba(245,158,11,0.08)',
                color: '#f59e0b', fontSize: '11px', fontWeight: 700,
                cursor: 'pointer', letterSpacing: '0.04em',
                flexShrink: 0,
              }}
            >
              Navigate ↗
            </button>

            {/* Proactive hint */}
            <div style={{
              flex: 1, minHeight: 0,
              borderRadius: '10px',
              background: 'rgba(110,231,183,0.05)',
              border: '1px solid rgba(110,231,183,0.12)',
              padding: '9px 10px',
              display: 'flex', flexDirection: 'column', gap: '5px',
              overflow: 'hidden',
            }}>
              <div style={{ fontSize: '9px', fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                ◆ DayPilot
              </div>
              <p style={{ fontSize: '10px', color: 'var(--muted)', lineHeight: 1.5, margin: 0 }}>
                Heading to <strong style={{ color: '#fff' }}>{upcoming.geo_segment?.destination}</strong> today — I'll watch your location and alert you when it's time to leave.
              </p>
            </div>
          </>
        ) : (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '7px', opacity: 0.42 }}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/>
              <circle cx="12" cy="9" r="2.5"/>
            </svg>
            <span style={{ fontSize: '11px', color: 'var(--muted)', textAlign: 'center' }}>No commute today</span>
          </div>
        )}

      </div>
    </div>
  );
}
