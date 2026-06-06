import { useState } from 'react';

function formatTime(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  if (isNaN(d)) return isoString;
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

const TYPE_ICONS = {
  deep_work: '◉',
  routine: '▣',
  break: '◌',
  geo: '◎',
  workout: '◈',
};

export default function TaskCard({ task, onToggle }) {
  const [expanded, setExpanded] = useState(false);
  const hasGeo = Boolean(task.geo_segment);

  function handleHeaderClick() {
    if (hasGeo) setExpanded((v) => !v);
  }

  const icon = task.icon || TYPE_ICONS[task.type] || '◆';
  const time = formatTime(task.start_time || task.scheduled_time);

  return (
    <article
      style={{
        borderRadius: 'var(--radius-lg)',
        border: '1px solid rgba(255,255,255,0.72)',
        background: 'linear-gradient(180deg, rgba(255,255,255,0.62), rgba(255,255,255,0.34))',
        boxShadow: '0 16px 38px rgba(24,30,27,0.05)',
        padding: '16px',
        position: 'relative',
        overflow: 'hidden',
        backdropFilter: 'blur(18px) saturate(130%)',
        opacity: task.done ? 0.6 : 1,
        transition: '170ms ease',
      }}
    >
      {/* header row */}
      <div
        role={hasGeo ? 'button' : undefined}
        tabIndex={hasGeo ? 0 : undefined}
        aria-expanded={hasGeo ? expanded : undefined}
        onClick={handleHeaderClick}
        onKeyDown={(e) => {
          if (hasGeo && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            setExpanded((v) => !v);
          }
        }}
        style={{
          display: 'grid',
          gridTemplateColumns: '24px minmax(0,1fr) auto auto',
          gap: '12px',
          alignItems: 'center',
          cursor: hasGeo ? 'pointer' : 'default',
        }}
      >
        {/* checkbox */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onToggle?.();
          }}
          aria-label={task.done ? 'Mark incomplete' : 'Mark complete'}
          style={{
            width: '20px',
            height: '20px',
            borderRadius: '7px',
            border: task.done ? 'none' : '1.5px solid rgba(21,29,25,0.18)',
            background: task.done
              ? 'linear-gradient(180deg, #dbe9dd, #9fc0a8)'
              : 'rgba(255,255,255,0.72)',
            color: task.done ? 'white' : 'transparent',
            display: 'grid',
            placeItems: 'center',
            fontSize: '12px',
            cursor: 'pointer',
            flexShrink: 0,
            boxShadow: task.done ? 'none' : 'inset 0 1px 0 rgba(255,255,255,0.58)',
          }}
        >
          {task.done ? '✓' : ''}
        </button>

        {/* title + meta */}
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: '15px',
              fontWeight: 650,
              letterSpacing: '-0.04em',
              lineHeight: 1.25,
              marginBottom: '4px',
              textDecoration: task.done ? 'line-through' : 'none',
              color: 'var(--text)',
            }}
          >
            {task.title}
          </div>
          {task.notes || task.meta ? (
            <div
              style={{
                color: 'var(--muted)',
                fontSize: '12px',
                lineHeight: 1.55,
              }}
            >
              {task.notes || task.meta}
            </div>
          ) : null}
        </div>

        {/* time pill */}
        <div
          style={{
            color: '#394440',
            fontVariantNumeric: 'tabular-nums',
            fontSize: '12px',
            fontWeight: 600,
            padding: '8px 10px',
            borderRadius: '999px',
            background: 'rgba(218, 232, 192, 0.34)',
            whiteSpace: 'nowrap',
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.55)',
          }}
        >
          {time}
        </div>

        {/* icon */}
        <div
          style={{
            width: '34px',
            height: '34px',
            borderRadius: '50%',
            display: 'grid',
            placeItems: 'center',
            background: 'rgba(184, 211, 188, 0.20)',
            color: hasGeo ? '#5a7a62' : '#6c8f77',
            fontSize: '14px',
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.46)',
            flexShrink: 0,
          }}
        >
          {hasGeo ? '◎' : icon}
        </div>
      </div>

      {/* geo panel */}
      {hasGeo && expanded && (
        <div style={{ marginTop: '14px', paddingLeft: '36px' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr auto',
              gap: '12px',
              padding: '14px',
              borderRadius: '18px',
              border: '1px solid rgba(21,29,25,0.06)',
              background: 'linear-gradient(180deg, rgba(239,244,231,0.86), rgba(255,255,255,0.64))',
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.5)',
            }}
          >
            <div>
              <div
                style={{
                  fontWeight: 650,
                  letterSpacing: '-0.03em',
                  marginBottom: '4px',
                  fontSize: '14px',
                }}
              >
                {task.geo_segment.origin} → {task.geo_segment.destination}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--muted)', lineHeight: 1.55 }}>
                Estimated travel time: {task.geo_segment.duration_text}
              </div>
              <div style={{ display: 'flex', gap: '8px', marginTop: '10px', flexWrap: 'wrap' }}>
                <span
                  style={{
                    fontSize: '11px',
                    color: '#44524b',
                    padding: '6px 10px',
                    borderRadius: '999px',
                    background: 'rgba(255,255,255,0.72)',
                    border: '1px solid rgba(21,29,25,0.06)',
                  }}
                >
                  Maps route ready
                </span>
              </div>
            </div>
            <button
              onClick={() =>
                window.open(task.geo_segment.maps_url, '_blank', 'noreferrer')
              }
              style={{
                alignSelf: 'center',
                border: 0,
                borderRadius: '14px',
                padding: '10px 12px',
                fontSize: '12px',
                fontWeight: 600,
                color: 'white',
                background: 'linear-gradient(135deg, #171d1b, #36413b)',
                cursor: 'pointer',
                boxShadow: '0 12px 24px rgba(24, 30, 27, 0.16)',
                whiteSpace: 'nowrap',
              }}
            >
              Navigate
            </button>
          </div>
        </div>
      )}
    </article>
  );
}
