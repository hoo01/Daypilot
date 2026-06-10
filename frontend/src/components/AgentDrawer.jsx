import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { storage } from '../utils/storage';
import { api } from '../utils/api';

export default function AgentDrawer({ open, onClose }) {
  const navigate = useNavigate();
  const { chatMessages, addMessage, isSending, setIsSending, refreshSchedule } = useStore();
  const [drawerHeight, setDrawerHeight] = useState(null); // px; null = use default 44%
  const [loadingStep, setLoadingStep]   = useState(0);
  const scrollRef             = useRef(null);
  const drawerRef             = useRef(null);
  const dragRef               = useRef(null);
  const inputRef              = useRef(null);

  function startResize(e) {
    const drawerEl = drawerRef.current;
    if (!drawerEl) return;
    dragRef.current = {
      startY: e.clientY,
      startHeight: drawerEl.getBoundingClientRect().height,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function doResize(e) {
    if (!dragRef.current) return;
    const { startY, startHeight } = dragRef.current;
    const parentHeight = drawerRef.current?.parentElement?.getBoundingClientRect().height ?? window.innerHeight;
    const delta = startY - e.clientY; // drag up => taller
    const min = parentHeight * 0.28;
    const max = parentHeight * 0.92;
    setDrawerHeight(Math.min(max, Math.max(min, startHeight + delta)));
  }

  function endResize(e) {
    dragRef.current = null;
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch {}
  }

  const LOADING_STEPS = [
    'Loading your context…',
    'Checking your goals…',
    'Reading your calendar…',
    'Analyzing your energy…',
    'Thinking about your day…',
  ];

  useEffect(() => {
    if (!isSending) { setLoadingStep(0); return; }
    const id = setInterval(() => setLoadingStep((s) => (s + 1) % LOADING_STEPS.length), 2500);
    return () => clearInterval(id);
  }, [isSending]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatMessages, open, isSending]);

  async function send() {
    const text = inputRef.current?.value.trim();
    if (!text || isSending) return;
    const userId    = storage.getUserId();
    const sessionId = storage.getSessionId();
    inputRef.current.value = '';
    setIsSending(true);
    addMessage({ role: 'user', text });
    try {
      const res = await api.chat(userId, text, sessionId);
      if (!sessionId && res.session_id) storage.setSessionId(res.session_id);
      addMessage({ role: 'agent', text: res.reply });
      if (res.schedule_updated) refreshSchedule(userId);
    } catch {
      addMessage({ role: 'agent', text: 'Sorry, something went wrong. Try again.' });
    } finally {
      setIsSending(false);
    }
  }

  return (
    <>
      {/* backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'absolute', inset: 0,
          background: 'rgba(4, 2, 14, 0.65)',
          opacity: open ? 1 : 0,
          pointerEvents: open ? 'auto' : 'none',
          transition: '240ms ease',
          zIndex: 20,
        }}
      />

      {/* drawer */}
      <div
        ref={drawerRef}
        aria-hidden={!open}
        className={`agent-drawer${isSending ? ' thinking' : ''}`}
        style={{
          position: 'absolute',
          left: '16px', right: '16px', bottom: '16px',
          height: drawerHeight != null ? `${drawerHeight}px` : '68%',
          borderRadius: '26px',
          transform: open ? 'translateY(0)' : 'translateY(112%)',
          opacity: open ? 1 : 0,
          transition: 'transform 280ms ease, opacity 250ms ease, border-color 350ms ease, box-shadow 350ms ease',
          zIndex: 25,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* grip — drag up/down to resize the drawer */}
        <div
          onPointerDown={startResize}
          onPointerMove={doResize}
          onPointerUp={endResize}
          onPointerCancel={endResize}
          style={{
            width: '100%', flexShrink: 0,
            padding: '10px 0 8px',
            display: 'flex', justifyContent: 'center',
            cursor: 'ns-resize',
            touchAction: 'none',
          }}
        >
          <div
            style={{
              width: '40px', height: '4px', borderRadius: '999px',
              background: 'rgba(255,255,255,0.18)',
            }}
          />
        </div>

        {/* head */}
        <div
          style={{
            padding: '16px 20px 14px',
            display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '14px',
            borderBottom: '1px solid rgba(255,255,255,0.08)',
          }}
        >
          <div>
            <div style={{ fontSize: '11px', letterSpacing: '0.20em', textTransform: 'uppercase', color: 'var(--muted-2)', marginBottom: '3px' }}>
              Agent mode
            </div>
            <h3 style={{ margin: 0, fontSize: '20px', fontWeight: 700, letterSpacing: '-0.05em', color: '#fff' }}>
              Quick ask
            </h3>
            <p style={{ margin: '5px 0 0', color: 'var(--muted)', fontSize: '13px', lineHeight: 1.5 }}>
              Ask DayPilot anything about your schedule.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
            <button
              onClick={() => { onClose(); navigate('/chat'); }}
              style={{
                padding: '8px 14px', borderRadius: '12px',
                border: '1px solid rgba(255,255,255,0.14)',
                background: 'rgba(255,255,255,0.08)',
                fontSize: '12px', fontWeight: 600, cursor: 'pointer', color: '#fff',
                transition: '160ms ease',
              }}
            >
              Open full chat →
            </button>
            <button
              onClick={onClose}
              aria-label="Close agent drawer"
              style={{
                width: '40px', height: '40px', borderRadius: '14px',
                border: '1px solid rgba(255,255,255,0.12)',
                background: 'rgba(255,255,255,0.07)',
                color: 'var(--muted)', cursor: 'pointer',
                display: 'grid', placeItems: 'center', fontSize: '14px',
              }}
            >
              ✕
            </button>
          </div>
        </div>

        {/* messages */}
        <div
          ref={scrollRef}
          style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 18px 8px', display: 'flex', flexDirection: 'column', gap: '10px' }}
        >
          {chatMessages.length === 0 && (
            <p style={{ color: 'var(--muted)', fontSize: '13px', textAlign: 'center', marginTop: '16px' }}>
              Start a conversation…
            </p>
          )}
          {chatMessages.map((msg, i) => (
            <div
              key={i}
              style={{
                maxWidth: '72%',
                alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                padding: '10px 14px',
                borderRadius: '16px',
                fontSize: '13px',
                lineHeight: 1.55,
                border: '1px solid rgba(255,255,255,0.10)',
                background: msg.role === 'user' ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.06)',
                color: '#fff',
              }}
            >
              <span style={{
                display: 'block', fontSize: '10px', letterSpacing: '0.10em', textTransform: 'uppercase',
                color: msg.role === 'user' ? 'var(--muted-2)' : 'var(--accent)',
                marginBottom: '5px', fontWeight: 600,
              }}>
                {msg.role === 'user' ? 'You' : '◆ DayPilot'}
              </span>
              <span style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</span>
            </div>
          ))}
          {isSending && (
            <div
              className="thinking-bubble"
              style={{
                alignSelf: 'flex-start',
                padding: '10px 14px',
                borderRadius: '16px',
                border: '1px solid rgba(110,231,183,0.18)',
                background: 'rgba(110,231,183,0.06)',
              }}
            >
              <span style={{ display: 'block', fontSize: '10px', letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: '7px', fontWeight: 600 }}>
                ◆ DayPilot
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.55)', fontStyle: 'italic' }}>
                  {LOADING_STEPS[loadingStep]}
                </span>
                <span style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                  {[0, 160, 320].map((delay) => (
                    <span
                      key={delay}
                      style={{
                        width: '5px', height: '5px', borderRadius: '50%',
                        background: 'var(--accent)',
                        display: 'inline-block',
                        animation: `thinking-bounce 1.2s ease-in-out ${delay}ms infinite`,
                      }}
                    />
                  ))}
                </span>
              </span>
            </div>
          )}
        </div>

        {/* compose */}
        <div
          style={{
            padding: '12px 16px 16px',
            borderTop: '1px solid rgba(255,255,255,0.08)',
            background: 'rgba(255,255,255,0.02)',
          }}
        >
          <div
            style={{
              borderRadius: '20px',
              border: '1px solid rgba(255,255,255,0.14)',
              background: 'rgba(255,255,255,0.07)',
              padding: '10px',
              display: 'flex', alignItems: 'center', gap: '12px',
            }}
          >
            <input
              ref={inputRef}
              defaultValue=""
              onKeyDown={(e) => e.key === 'Enter' && send()}
              placeholder="Ask DayPilot to replan, explain, or summarize..."
              style={{
                flex: 1, border: 0, outline: 'none',
                background: 'transparent', color: '#fff',
                fontSize: '13px', letterSpacing: '0.01em',
              }}
            />
            <button
              onClick={send}
              disabled={isSending}
              style={{
                width: '40px', height: '40px', borderRadius: '14px',
                border: '1px solid rgba(110,231,183,0.28)',
                background: 'rgba(110,231,183,0.12)',
                color: 'var(--accent)', cursor: 'pointer',
                display: 'grid', placeItems: 'center', fontSize: '16px', flexShrink: 0,
                opacity: isSending ? 0.40 : 1,
                transition: '160ms ease',
              }}
            >
              ↑
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
