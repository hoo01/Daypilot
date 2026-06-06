import { useNavigate, useLocation } from 'react-router-dom';

const NAV = [
  { path: '/today', label: 'Today', icon: '⊞' },
  { path: '/chat',  label: 'Chat',  icon: '⊹' },
  { path: '/history', label: 'History', icon: '⊫', disabled: true },
];

export default function NavRail({ onOpenAgentDrawer }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  return (
    <aside
      style={{
        width: '84px',
        borderRadius: 'var(--radius-xl)',
        border: '1px solid rgba(255,255,255,0.66)',
        background: 'rgba(255,255,255,0.38)',
        backdropFilter: 'var(--glass)',
        boxShadow: 'var(--shadow-soft)',
        padding: '16px 10px',
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
              border: active ? '1px solid var(--line)' : '1px solid transparent',
              background: active ? 'rgba(255,255,255,0.82)' : 'transparent',
              color: '#2c3531',
              display: 'grid',
              placeItems: 'center',
              fontSize: '18px',
              cursor: disabled ? 'default' : 'pointer',
              opacity: disabled ? 0.38 : 1,
              boxShadow: active ? '0 10px 22px rgba(24,30,27,0.07)' : 'none',
              transition: '180ms ease',
            }}
          >
            {icon}
          </button>
        );
      })}

      <div style={{ flex: 1 }} />

      <button
        title="Settings"
        style={{
          width: '50px',
          height: '50px',
          borderRadius: '18px',
          border: '1px solid transparent',
          background: 'transparent',
          color: '#2c3531',
          display: 'grid',
          placeItems: 'center',
          fontSize: '18px',
          cursor: 'pointer',
          opacity: 0.5,
        }}
      >
        ⚙
      </button>
    </aside>
  );
}
