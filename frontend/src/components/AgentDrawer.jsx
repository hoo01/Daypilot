import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useStore } from '../store/useStore';
import { storage } from '../utils/storage';
import { api } from '../utils/api';

export default function AgentDrawer({ open, onClose }) {
  const navigate = useNavigate();
  const { chatMessages, addMessage } = useStore();
  const [input, setInput]     = useState('');
  const [sending, setSending] = useState(false);
  const scrollRef             = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatMessages, open, sending]);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    const userId    = storage.getUserId();
    const sessionId = storage.getSessionId();
    setInput('');
    setSending(true);
    addMessage({ role: 'user', text });
    try {
      const res = await api.chat(userId, text, sessionId);
      if (!sessionId && res.session_id) storage.setSessionId(res.session_id);
      addMessage({ role: 'agent', text: res.reply });
    } catch {
      addMessage({ role: 'agent', text: 'Sorry, something went wrong. Try again.' });
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      {/* backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'absolute', inset: 0,
          background: 'rgba(4, 2, 14, 0.55)',
          backdropFilter: 'blur(8px)',
          opacity: open ? 1 : 0,
          pointerEvents: open ? 'auto' : 'none',
          transition: '240ms ease',
          zIndex: 20,
        }}
      />

      {/* drawer */}
      <div
        aria-hidden={!open}
        style={{
          position: 'absolute',
          left: '16px', right: '16px', bottom: '16px',
          height: '44%',
          borderRadius: '26px',
          border: '1px solid rgba(255,255,255,0.14)',
          background: 'rgba(10, 7, 28, 0.82)',
          backdropFilter: 'blur(28px) saturate(180%)',
          boxShadow: '0 32px 80px rgba(0,0,0,0.50)',
          transform: open ? 'translateY(0)' : 'translateY(112%)',
          opacity: open ? 1 : 0,
          transition: 'transform 280ms ease, opacity 250ms ease',
          zIndex: 25,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* grip */}
        <div
          style={{
            width: '40px', height: '4px', borderRadius: '999px',
            background: 'rgba(255,255,255,0.18)',
            margin: '12px auto 0',
          }}
        />

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
              {msg.role === 'user' ? (
                msg.text
              ) : (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p:      ({ children }) => <p style={{ margin: '0 0 4px', lineHeight: 1.55 }}>{children}</p>,
                    ul:     ({ children }) => <ul style={{ margin: '3px 0', paddingLeft: '16px' }}>{children}</ul>,
                    ol:     ({ children }) => <ol style={{ margin: '3px 0', paddingLeft: '16px' }}>{children}</ol>,
                    li:     ({ children }) => <li style={{ marginBottom: '2px' }}>{children}</li>,
                    strong: ({ children }) => <strong style={{ fontWeight: 700, color: '#fff' }}>{children}</strong>,
                    code:   ({ children }) => <code style={{ background: 'rgba(255,255,255,0.12)', borderRadius: '4px', padding: '1px 5px', fontSize: '11px', color: 'var(--accent-2)' }}>{children}</code>,
                  }}
                >
                  {msg.text}
                </ReactMarkdown>
              )}
            </div>
          ))}
          {sending && (
            <div style={{
              alignSelf: 'flex-start',
              padding: '10px 14px',
              borderRadius: '16px',
              border: '1px solid rgba(110,231,183,0.18)',
              background: 'rgba(110,231,183,0.06)',
            }}>
              <span style={{ display: 'block', fontSize: '10px', letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: '7px', fontWeight: 600 }}>
                ◆ DayPilot
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
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
              value={input}
              onChange={(e) => setInput(e.target.value)}
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
              disabled={sending || !input.trim()}
              style={{
                width: '40px', height: '40px', borderRadius: '14px',
                border: '1px solid rgba(110,231,183,0.28)',
                background: 'rgba(110,231,183,0.12)',
                color: 'var(--accent)', cursor: 'pointer',
                display: 'grid', placeItems: 'center', fontSize: '16px', flexShrink: 0,
                opacity: sending || !input.trim() ? 0.40 : 1,
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
