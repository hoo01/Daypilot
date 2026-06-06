import { useNavigate } from 'react-router-dom';

export default function Toast({ message, onDismiss }) {
  const navigate = useNavigate();

  function handleAskInChat() {
    onDismiss();
    navigate('/chat?trigger=feedback');
  }

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '80px',
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 500,
        background: 'var(--surface-strong)',
        backdropFilter: 'var(--glass)',
        border: '1px solid var(--line-strong)',
        borderRadius: 'var(--radius-md)',
        boxShadow: 'var(--shadow-soft)',
        padding: '14px 18px',
        display: 'flex',
        alignItems: 'center',
        gap: '16px',
        minWidth: '300px',
        maxWidth: '480px',
        color: 'var(--text)',
      }}
    >
      <span style={{ flex: 1, fontSize: '13px', lineHeight: 1.55 }}>{message}</span>
      <button
        onClick={handleAskInChat}
        style={{
          whiteSpace: 'nowrap',
          fontSize: '12px',
          fontWeight: 600,
          color: '#2c3531',
          background: 'rgba(218, 232, 192, 0.5)',
          border: '1px solid var(--line)',
          borderRadius: '999px',
          padding: '8px 12px',
          cursor: 'pointer',
        }}
      >
        Ask in chat →
      </button>
      <button
        onClick={onDismiss}
        aria-label="Dismiss"
        style={{
          width: '28px',
          height: '28px',
          border: '1px solid var(--line)',
          borderRadius: '50%',
          background: 'rgba(255,255,255,0.6)',
          color: 'var(--muted)',
          fontSize: '12px',
          display: 'grid',
          placeItems: 'center',
          cursor: 'pointer',
          flexShrink: 0,
        }}
      >
        ✕
      </button>
    </div>
  );
}
