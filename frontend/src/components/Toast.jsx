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
        background: 'rgba(10, 7, 28, 0.88)',
        backdropFilter: 'blur(20px)',
        border: '1px solid rgba(255,255,255,0.14)',
        borderRadius: '16px',
        boxShadow: '0 16px 48px rgba(0,0,0,0.40)',
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
          color: 'var(--accent)',
          background: 'transparent',
          border: '1px solid var(--accent-3)',
          borderRadius: 'var(--radius-sm)',
          padding: '6px 12px',
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
          borderRadius: 'var(--radius-sm)',
          background: 'transparent',
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
