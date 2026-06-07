import { useEffect, useRef, useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { api } from '../utils/api';
import NavRail from './NavRail';
import BackendBanner from './BackendBanner';
import AgentDrawer from './AgentDrawer';

export default function Shell() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const setIsBackendDown = useStore((s) => s.setIsBackendDown);
  const isBackendDown    = useStore((s) => s.isBackendDown);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const pollRef = useRef(null);

  async function checkHealth() {
    try {
      const data = await api.health();
      setIsBackendDown(data.status !== 'ok');
    } catch {
      setIsBackendDown(true);
    }
  }

  useEffect(() => {
    checkHealth();
    pollRef.current = setInterval(checkHealth, 30_000);
    return () => clearInterval(pollRef.current);
  }, []);

  const isToday = pathname.startsWith('/today');
  const isChat  = pathname.startsWith('/chat');
  const tab     = isToday ? 'Today' : isChat ? 'Chat' : 'History';

  const dateLabel = new Intl.DateTimeFormat('en-US', {
    weekday: 'short', month: 'short', day: 'numeric',
  }).format(new Date());

  return (
    <div style={{ width: '100%', height: '100vh', padding: '10px' }}>
      <BackendBanner />

      <div
        style={{
          height: '100%',
          borderRadius: '28px',
          overflow: 'hidden',
          position: 'relative',
          border: '1px solid rgba(255,255,255,0.10)',
          background: 'rgba(8, 5, 24, 0.68)',
          backdropFilter: 'blur(32px) saturate(160%)',
          boxShadow: '0 32px 100px rgba(0,0,0,0.52)',
        }}
      >
        {/* topbar */}
        <header
          style={{
            position: 'relative',
            zIndex: 5,
            height: '62px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            padding: '0 20px',
            borderBottom: '1px solid rgba(255,255,255,0.08)',
            background: 'rgba(255,255,255,0.03)',
          }}
        >
          {/* brand */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              fontSize: '18px',
              fontWeight: 700,
              letterSpacing: '-0.04em',
              color: '#fff',
            }}
          >
            <div
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '13px',
                display: 'grid',
                placeItems: 'center',
                background: 'linear-gradient(135deg, rgba(110,231,183,0.22), rgba(52,211,153,0.14))',
                border: '1px solid rgba(110,231,183,0.28)',
                color: 'var(--accent)',
                fontSize: '15px',
              }}
            >
              ◆
            </div>
            DayPilot
          </div>

          {/* right side */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {/* tabs */}
            <div
              style={{
                display: 'inline-flex',
                padding: '4px',
                gap: '4px',
                borderRadius: '999px',
                border: '1px solid rgba(255,255,255,0.10)',
                background: 'rgba(255,255,255,0.06)',
              }}
            >
              {['Today', 'Chat'].map((t) => (
                <button
                  key={t}
                  onClick={() => navigate(`/${t.toLowerCase()}`)}
                  style={{
                    border: tab === t ? '1px solid rgba(255,255,255,0.22)' : '1px solid transparent',
                    borderRadius: '999px',
                    background: tab === t ? 'rgba(255,255,255,0.16)' : 'transparent',
                    padding: '6px 14px',
                    fontFamily: 'inherit',
                    fontSize: '12px',
                    fontWeight: 600,
                    color: tab === t ? '#fff' : 'var(--muted)',
                    cursor: 'pointer',
                    transition: '160ms ease',
                    letterSpacing: '0.02em',
                  }}
                >
                  {t}
                </button>
              ))}
            </div>

            {/* date */}
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 11px',
                borderRadius: '999px',
                background: 'rgba(255,255,255,0.07)',
                border: '1px solid rgba(255,255,255,0.10)',
                color: 'var(--muted)',
                fontSize: '12px',
                whiteSpace: 'nowrap',
              }}
            >
              <span
                style={{
                  width: '7px', height: '7px',
                  borderRadius: '50%',
                  background: 'var(--accent)',
                  flexShrink: 0,
                }}
              />
              {dateLabel}
            </div>

            {/* AI */}
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 11px',
                borderRadius: '999px',
                background: 'rgba(255,255,255,0.07)',
                border: '1px solid rgba(255,255,255,0.10)',
                color: 'var(--muted)',
                fontSize: '12px',
                whiteSpace: 'nowrap',
              }}
            >
              <span
                style={{
                  width: '7px', height: '7px',
                  borderRadius: '50%',
                  background: 'var(--accent)',
                  flexShrink: 0,
                  animation: 'pulse-dot 2.4s ease-in-out infinite',
                }}
              />
              AI
            </div>

            {/* backend */}
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 11px',
                borderRadius: '999px',
                background: 'rgba(255,255,255,0.07)',
                border: isBackendDown ? '1px solid rgba(248,113,113,0.40)' : '1px solid rgba(255,255,255,0.10)',
                color: isBackendDown ? 'var(--error)' : 'var(--muted)',
                fontSize: '12px',
                whiteSpace: 'nowrap',
              }}
            >
              <span
                style={{
                  width: '7px', height: '7px',
                  borderRadius: '50%',
                  background: isBackendDown ? 'var(--error)' : 'var(--accent-3)',
                  flexShrink: 0,
                }}
              />
              {isBackendDown ? 'Offline' : 'Backend'}
            </div>
          </div>
        </header>

        {/* content */}
        <div
          style={{
            height: 'calc(100% - 62px)',
            display: 'grid',
            gridTemplateColumns: '72px minmax(0, 1fr)',
            gridTemplateRows: '1fr',
            gap: '12px',
            padding: '12px',
            position: 'relative',
            zIndex: 2,
          }}
        >
          <NavRail />
          <Outlet context={{ openAgentDrawer: () => setDrawerOpen(true) }} />
        </div>

        <AgentDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      </div>
    </div>
  );
}
