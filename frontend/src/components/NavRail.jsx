import { useNavigate, useLocation } from 'react-router-dom';
import { storage } from '../utils/storage';

const NAV = [
  { path: '/today',   label: 'Today',   icon: '⊞' },
  { path: '/chat',    label: 'Chat',    icon: '⊹' },
  { path: '/history', label: 'History', icon: '⊫', disabled: true },
];

export default function NavRail({ onOpenAgentDrawer }) {
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
        border: '1px solid rgba(255,255,255,0.10)',
        background: 'rgba(255,255,255,0.08)',
        backdropFilter: 'var(--glass)',
        padding: '14px 8px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '10px',
      }}
    >
      {NAV.map(({ path, label, icon, disabled }) => {
        const active = pathname.startsWith(path);
        return (
          <button
            key={path}
            title={label}
            disabled={disabled}
            onClick={() => !disabled && navigate(path)}
            style={{
              width: '50px',
              height: '50px',
              borderRadius: '18px',
              border: active ? '1px solid rgba(255,255,255,0.22)' : '1px solid transparent',
              background: active ? 'rgba(255,255,255,0.16)' : 'transparent',
              color: active ? '#fff' : 'var(--muted)',
              display: 'grid',
              placeItems: 'center',
              fontSize: '18px',
              cursor: disabled ? 'default' : 'pointer',
              opacity: disabled ? 0.28 : 1,
              boxShadow: active ? '0 8px 24px rgba(0,0,0,0.20)' : 'none',
              transition: '160ms ease',
            }}
          >
            {icon}
          </button>
        );
      })}

      <div style={{ flex: 1 }} />

      <button
        title="Sign out"
        onClick={handleLogout}
        style={{
          width: '50px',
          height: '50px',
          borderRadius: '18px',
          border: '1px solid transparent',
          background: 'transparent',
          color: 'var(--muted)',
          display: 'grid',
          placeItems: 'center',
          fontSize: '16px',
          cursor: 'pointer',
          opacity: 0.65,
          transition: '160ms ease',
        }}
      >
        ⏻
      </button>
    </aside>
  );
}
