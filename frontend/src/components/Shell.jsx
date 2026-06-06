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
  const isBackendDown = useStore((s) => s.isBackendDown);
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
  const isChat = pathname.startsWith('/chat');

  const tab = isToday ? 'Today' : isChat ? 'Chat' : 'History';

  const dateLabel = new Intl.DateTimeFormat('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  }).format(new Date());

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        padding: '20px',
      }}
    >
      <BackendBanner />

      <div
        style={{
          height: '100%',
          borderRadius: '34px',
          overflow: 'hidden',
          position: 'relative',
          border: '1px solid rgba(255,255,255,0.68)',
          background: 'linear-gradient(180deg, rgba(255,255,255,0.38), rgba(255,255,255,0.18))',
          backdropFilter: 'var(--glass)',
          boxShadow: 'var(--shadow)',
        }}
      >
        {/* topbar */}
        <header
          style={{
            position: 'relative',
            zIndex: 5,
            height: '80px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '18px',
            padding: '0 28px 0 24px',
          }}
        >
          {/* brand */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              letterSpacing: '-0.05em',
              fontSize: '18px',
              fontWeight: 700,
            }}
          >
            <div
              style={{
                width: '38px',
                height: '38px',
                borderRadius: '14px',
                display: 'grid',
                placeItems: 'center',
                color: 'white',
                background: 'linear-gradient(145deg, #141917, #2d3632)',
                boxShadow: '0 14px 28px rgba(20,24,22,0.2)',
                fontSize: '16px',
              }}
            >
              ◆
            </div>
            <div>DayPilot</div>
          </div>

          {/* right side */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {/* tabs */}
            <div
              style={{
                display: 'inline-flex',
                padding: '4px',
                gap: '4px',
                borderRadius: '999px',
                border: '1px solid rgba(21,29,25,0.08)',
                background: 'rgba(255,255,255,0.38)',
                boxShadow: '0 8px 22px rgba(24,30,27,0.04)',
                backdropFilter: 'blur(12px) saturate(120%)',
              }}
            >
              {['Today', 'Chat'].map((t) => (
                <button
                  key={t}
                  onClick={() => navigate(`/${t.toLowerCase()}`)}
                  style={{
                    border: 0,
                    borderRadius: '999px',
                    background: tab === t ? 'rgba(255,255,255,0.72)' : 'transparent',
                    padding: '10px 14px',
                    fontFamily: 'inherit',
                    fontSize: '13px',
                    fontWeight: 600,
                    letterSpacing: '0.02em',
                    color: tab === t ? 'var(--text)' : 'var(--muted)',
                    cursor: 'pointer',
                    boxShadow: tab === t ? '0 10px 20px rgba(23,31,27,0.05)' : 'none',
                    transition: '180ms ease',
                  }}
                >
                  {t}
                </button>
              ))}
            </div>

            {/* date chip */}
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 14px',
                borderRadius: '999px',
                background: 'rgba(255,255,255,0.56)',
                border: '1px solid rgba(21,29,25,0.08)',
                color: '#2c3531',
                fontSize: '13px',
                whiteSpace: 'nowrap',
                boxShadow: '0 8px 22px rgba(24,30,27,0.04)',
                backdropFilter: 'blur(12px) saturate(120%)',
              }}
            >
              <span
                style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: 'linear-gradient(180deg, #d7ead9, #8fb99a)',
                  boxShadow: '0 0 0 4px rgba(169, 203, 176, 0.12)',
                  flexShrink: 0,
                }}
              />
              {dateLabel}
            </div>

            {/* backend status chip */}
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 14px',
                borderRadius: '999px',
                background: 'rgba(255,255,255,0.56)',
                border: '1px solid rgba(21,29,25,0.08)',
                color: '#2c3531',
                fontSize: '13px',
                whiteSpace: 'nowrap',
                boxShadow: '0 8px 22px rgba(24,30,27,0.04)',
                backdropFilter: 'blur(12px) saturate(120%)',
              }}
            >
              Backend{' '}
              <strong style={{ color: isBackendDown ? 'var(--error)' : undefined }}>
                {isBackendDown ? 'Offline' : 'Healthy'}
              </strong>
            </div>
          </div>
        </header>

        {/* content */}
        <div
          style={{
            height: 'calc(100% - 80px)',
            display: 'grid',
            gridTemplateColumns: '84px minmax(0, 1fr)',
            gap: '16px',
            padding: '0 16px 16px',
            position: 'relative',
            zIndex: 2,
          }}
        >
          <NavRail />
          <Outlet context={{ openAgentDrawer: () => setDrawerOpen(true) }} />
        </div>

        {/* agent drawer — lives inside shell so it can overlay the content */}
        <AgentDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      </div>
    </div>
  );
}
