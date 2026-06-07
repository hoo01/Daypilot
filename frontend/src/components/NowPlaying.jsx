import { useState } from 'react';

const PLAYLIST = [
  { title: 'Lo-fi Study Beats', artist: 'Chillhop Music', progress: 38 },
  { title: 'Deep Work Flow', artist: 'Brain.fm', progress: 12 },
  { title: 'Focus Radio', artist: 'Endel', progress: 61 },
];

export default function NowPlaying() {
  const [playing, setPlaying] = useState(false);
  const [idx] = useState(0);
  const track = PLAYLIST[idx];

  return (
    <div style={{ padding: '12px 14px 14px' }}>
      <div
        style={{
          fontSize: '10px',
          fontWeight: 700,
          color: 'var(--muted)',
          letterSpacing: '0.07em',
          textTransform: 'uppercase',
          marginBottom: '10px',
        }}
      >
        Now Playing
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {/* album art placeholder */}
        <div
          style={{
            width: '40px',
            height: '40px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #2e3d35, #5a7a62)',
            flexShrink: 0,
            display: 'grid',
            placeItems: 'center',
            fontSize: '16px',
            color: 'rgba(255,255,255,0.75)',
            boxShadow: '0 8px 18px rgba(24,30,27,0.15)',
          }}
        >
          ♪
        </div>

        {/* track info */}
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: '13px',
              fontWeight: 650,
              letterSpacing: '-0.03em',
              color: 'var(--text)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {track.title}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '2px' }}>
            {track.artist}
          </div>
        </div>

        {/* play/pause */}
        <button
          onClick={() => setPlaying((p) => !p)}
          style={{
            width: '30px',
            height: '30px',
            borderRadius: '50%',
            border: 0,
            background: 'linear-gradient(135deg, #161d1b, #36423c)',
            color: 'white',
            cursor: 'pointer',
            display: 'grid',
            placeItems: 'center',
            fontSize: '10px',
            flexShrink: 0,
            boxShadow: '0 8px 18px rgba(24,30,27,0.18)',
          }}
        >
          {playing ? '❚❚' : '▶'}
        </button>
      </div>

      {/* progress bar */}
      <div
        style={{
          marginTop: '10px',
          height: '3px',
          borderRadius: '999px',
          background: 'rgba(21,29,25,0.08)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${track.progress}%`,
            height: '100%',
            borderRadius: 'inherit',
            background: 'linear-gradient(90deg, var(--accent-4), var(--accent-2))',
          }}
        />
      </div>
    </div>
  );
}
