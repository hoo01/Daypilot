import { useNavigate, useLocation } from 'react-router-dom';
import { storage } from '../utils/storage';

function IconCalendar() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
      <line x1="16" y1="2" x2="16" y2="6"/>
      <line x1="8" y1="2" x2="8" y2="6"/>
      <line x1="3" y1="10" x2="21" y2="10"/>
    </svg>
  );
}

function IconChat() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>
  );
}

function IconSettings() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
  );
}

const NAV = [
  { path: '/today', label: 'Today', Icon: IconCalendar },
  { path: '/chat',  label: 'Chat',  Icon: IconChat     },
];

export default function NavRail() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  function handleLogout() {
    storage.clear();
    navigate('/auth', { replace: true });
  }

  return (
    <aside
      style={{
        width: '72px',
        borderRadius: 'var(--radius-xl)',
        background: 'rgba(255,255,255,0.07)',
        backdropFilter: 'var(--glass)',
        padding: '14px 8px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '10px',
      }}
    >
      {NAV.map(({ path, label, Icon }) => {
        const active = pathname.startsWith(path);
        return (
          <button
            key={path}
            title={label}
            className="nav-btn"
            onClick={() => navigate(path)}
            style={{
              width: '50px',
              height: '50px',
              borderRadius: '18px',
              border: 'none',
              background: active ? 'rgba(255,255,255,0.16)' : 'transparent',
              color: active ? '#fff' : 'var(--muted)',
              display: 'grid',
              placeItems: 'center',
              cursor: 'pointer',
              boxShadow: active ? '0 8px 24px rgba(0,0,0,0.22), 0 0 0 1px rgba(255,255,255,0.12)' : 'none',
            }}
          >
            <Icon />
          </button>
        );
      })}

      <div style={{ flex: 1 }} />

      <button
        title="Settings"
        className="nav-btn"
        onClick={handleLogout}
        style={{
          width: '50px',
          height: '50px',
          borderRadius: '18px',
          border: 'none',
          background: 'transparent',
          color: 'var(--muted)',
          display: 'grid',
          placeItems: 'center',
          cursor: 'pointer',
        }}
      >
        <IconSettings />
      </button>
    </aside>
  );
}
