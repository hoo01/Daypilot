const QUICK_ACTIONS = ['Reschedule', 'Add task', 'Explain day'];

export default function AgentStatusCard({ onOpen }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onOpen?.()}
      style={{
        padding: '14px',
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
      }}
    >
      {/* status row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span
          style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: 'linear-gradient(180deg, #a8dbb0, #5a9e6a)',
            flexShrink: 0,
            animation: 'pulse-dot 2.4s ease-in-out infinite',
          }}
        />
        <span
          style={{
            fontSize: '13px',
            fontWeight: 700,
            letterSpacing: '-0.03em',
            color: 'var(--text)',
          }}
        >
          AI Agent
        </span>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '10px',
            padding: '3px 8px',
            borderRadius: '999px',
            background: 'rgba(74, 145, 102, 0.12)',
            color: '#2d6642',
            fontWeight: 600,
            border: '1px solid rgba(74, 145, 102, 0.28)',
            letterSpacing: '0.02em',
          }}
        >
          Active
        </span>
      </div>

      {/* description */}
      <p
        style={{
          margin: 0,
          fontSize: '12px',
          color: 'var(--muted)',
          lineHeight: 1.55,
        }}
      >
        DayPilot is watching your day. Ask it to adjust anything.
      </p>

      {/* quick-action tags */}
      <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
        {QUICK_ACTIONS.map((a) => (
          <span
            key={a}
            style={{
              fontSize: '11px',
              padding: '4px 9px',
              borderRadius: '999px',
              background: 'rgba(255,255,255,0.62)',
              border: '1px solid rgba(21,29,25,0.08)',
              color: '#394440',
              fontWeight: 500,
            }}
          >
            {a}
          </span>
        ))}
      </div>
    </div>
  );
}
