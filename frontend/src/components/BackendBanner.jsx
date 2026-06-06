import { useStore } from '../store/useStore';

export default function BackendBanner() {
  const isBackendDown = useStore((s) => s.isBackendDown);
  if (!isBackendDown) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        height: '48px',
        background: 'var(--error)',
        color: '#fff',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: '13px',
        fontWeight: 600,
        letterSpacing: '0.01em',
      }}
    >
      DayPilot is currently unavailable. Please try again shortly.
    </div>
  );
}
