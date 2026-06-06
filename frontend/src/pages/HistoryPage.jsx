export default function HistoryPage() {
  return (
    <div
      style={{
        height: '100%',
        borderRadius: 'var(--radius-xl)',
        border: '1px solid rgba(255,255,255,0.66)',
        background: 'rgba(255,255,255,0.38)',
        backdropFilter: 'var(--glass)',
        boxShadow: 'var(--shadow-soft)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column',
        gap: '12px',
      }}
    >
      <div style={{ fontSize: '32px', opacity: 0.4 }}>⊫</div>
      <h2
        style={{
          margin: 0,
          fontSize: '20px',
          fontWeight: 700,
          letterSpacing: '-0.05em',
          color: 'var(--text)',
        }}
      >
        History
      </h2>
      <p style={{ fontSize: '13px', color: 'var(--muted)', margin: 0 }}>
        Coming in phase 2.
      </p>
    </div>
  );
}
