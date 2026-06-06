import { useState } from 'react';
import { api } from '../utils/api';
import { storage } from '../utils/storage';

function generateUserId() {
  return 'user_' + Math.random().toString(36).slice(2, 10);
}

export default function AuthPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleGoogleLogin() {
    setLoading(true);
    setError(null);
    try {
      let userId = storage.getUserId();
      if (!userId) {
        userId = generateUserId();
        storage.setUserId(userId);
      }
      const { auth_url } = await api.getAuthUrl(userId);
      window.location.href = auth_url;
    } catch (err) {
      setError('Could not connect to DayPilot. Please try again.');
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background:
          'radial-gradient(900px 620px at 14% 12%, rgba(184,211,188,0.35), transparent 56%), ' +
          'radial-gradient(760px 520px at 88% 18%, rgba(218,232,192,0.32), transparent 54%), ' +
          'linear-gradient(180deg, #f3f7f1 0%, #ebf1eb 100%)',
      }}
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '32px',
          padding: '48px 40px',
          borderRadius: 'var(--radius-xl)',
          border: '1px solid rgba(255,255,255,0.72)',
          background: 'linear-gradient(180deg, rgba(255,255,255,0.62), rgba(255,255,255,0.38))',
          backdropFilter: 'var(--glass)',
          boxShadow: 'var(--shadow)',
          minWidth: '340px',
          maxWidth: '420px',
          width: '90%',
        }}
      >
        {/* brand mark */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            style={{
              width: '52px',
              height: '52px',
              borderRadius: '18px',
              display: 'grid',
              placeItems: 'center',
              color: 'white',
              background: 'linear-gradient(145deg, #141917, #2d3632)',
              boxShadow: '0 14px 28px rgba(20,24,22,0.2)',
              fontSize: '22px',
            }}
          >
            ◆
          </div>
          <div
            style={{
              fontSize: '26px',
              fontWeight: 700,
              letterSpacing: '-0.05em',
              color: 'var(--text)',
            }}
          >
            DayPilot
          </div>
        </div>

        {/* tagline */}
        <p
          style={{
            fontSize: '14px',
            color: 'var(--muted)',
            textAlign: 'center',
            lineHeight: 1.6,
            margin: 0,
          }}
        >
          Your AI-native daily co-pilot
        </p>

        {/* google button */}
        <button
          onClick={handleGoogleLogin}
          disabled={loading}
          style={{
            width: '100%',
            padding: '14px 24px',
            borderRadius: '16px',
            border: '1px solid rgba(21,29,25,0.10)',
            background: loading
              ? 'rgba(255,255,255,0.5)'
              : 'linear-gradient(180deg, rgba(255,255,255,0.72), rgba(255,255,255,0.50))',
            boxShadow: '0 12px 24px rgba(24,30,27,0.08)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '12px',
            fontSize: '14px',
            fontWeight: 600,
            color: 'var(--text)',
            cursor: loading ? 'not-allowed' : 'pointer',
            opacity: loading ? 0.7 : 1,
            transition: '160ms ease',
          }}
        >
          {/* Google "G" mark — simplified */}
          <svg width="20" height="20" viewBox="0 0 48 48" fill="none">
            <path d="M44.5 20H24v8.5h11.8C34.7 33.9 30.1 37 24 37c-7.2 0-13-5.8-13-13s5.8-13 13-13c3.1 0 5.9 1.1 8.1 2.9l6.4-6.4C34.6 4.1 29.6 2 24 2 11.8 2 2 11.8 2 24s9.8 22 22 22c11 0 21-8 21-22 0-1.3-.2-2.7-.5-4z" fill="#FFC107"/>
            <path d="M6.3 14.7l7 5.1C15.1 16 19.2 13 24 13c3.1 0 5.9 1.1 8.1 2.9l6.4-6.4C34.6 4.1 29.6 2 24 2 16.3 2 9.6 7.3 6.3 14.7z" fill="#FF3D00"/>
            <path d="M24 46c5.5 0 10.5-1.8 14.4-5l-6.7-5.5C29.7 37 27 38 24 38c-6 0-10.6-3-11.7-7.3l-7 5.4C8.8 42.3 15.8 46 24 46z" fill="#4CAF50"/>
            <path d="M44.5 20H24v8.5h11.8c-.5 2.5-2 4.7-4.1 6.2l6.7 5.5C42 37.3 45 31.2 45 24c0-1.3-.2-2.7-.5-4z" fill="#1976D2"/>
          </svg>
          {loading ? 'Connecting...' : 'Continue with Google'}
        </button>

        {error && (
          <p
            style={{
              fontSize: '12px',
              color: 'var(--error)',
              textAlign: 'center',
              margin: 0,
            }}
          >
            {error}
          </p>
        )}

        <p style={{ fontSize: '11px', color: 'var(--muted-2)', textAlign: 'center', margin: 0 }}>
          DayPilot reads your calendar to build a smart daily plan.
        </p>
      </div>
    </div>
  );
}
