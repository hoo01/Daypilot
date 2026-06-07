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
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatMessages, open]);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    const userId = storage.getUserId();
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
          position: 'absolute',
          inset: 0,
          background: 'rgba(242,247,241,0.24)',
          backdropFilter: 'blur(6px)',
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
          left: '16px',
          right: '16px',
          bottom: '16px',
          height: '44%',
          borderRadius: '30px',
          border: '1px solid rgba(255,255,255,0.72)',
          background: 'linear-gradient(180deg, rgba(255,255,255,0.54), rgba(255,255,255,0.34))',
          boxShadow: '0 24px 70px rgba(24,30,27,0.14)',
          backdropFilter: 'blur(24px) saturate(140%)',
          transform: open ? 'translateY(0)' : 'translateY(112%)',
          opacity: open ? 1 : 0,
          transition: 'transform 280ms ease, opacity 280ms ease',
          zIndex: 25,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* grip */}
        <div
          style={{
            width: '72px',
            height: '6px',
            borderRadius: '999px',
            background: 'rgba(21,29,25,0.14)',
            margin: '12px auto 0',
          }}
        />

        {/* head */}
        <div
          style={{
            padding: '18px 20px 14px',
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: '14px',
          }}
        >
          <div>
            <div
              style={{
                fontSize: '11px',
                letterSpacing: '0.22em',
                textTransform: 'uppercase',
                color: 'var(--muted-2)',
              }}
            >
              Agent mode
            </div>
            <h3
              style={{
                margin: '4px 0 0',
                fontSize: '22px',
                fontWeight: 700,
                letterSpacing: '-0.07em',
              }}
            >
              Quick ask
            </h3>
            <p style={{ margin: '6px 0 0', color: 'var(--muted)', fontSize: '13px', lineHeight: 1.5 }}>
              Ask DayPilot anything about your schedule.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
            <button
              onClick={() => { onClose(); navigate('/chat'); }}
              style={{
                padding: '8px 12px',
                borderRadius: '14px',
                border: '1px solid var(--line)',
                background: 'rgba(255,255,255,0.6)',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                color: '#31403a',
              }}
            >
              Open full chat →
            </button>
            <button
              onClick={onClose}
              aria-label="Close agent drawer"
              style={{
                width: '42px',
                height: '42px',
                borderRadius: '16px',
                border: '1px solid rgba(21,29,25,0.08)',
                background: 'rgba(255,255,255,0.6)',
                color: '#31403a',
                cursor: 'pointer',
                display: 'grid',
                placeItems: 'center',
                fontSize: '14px',
              }}
            >
              ✕
            </button>
          </div>
        </div>

        {/* messages */}
        <div
          ref={scrollRef}
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            padding: '0 18px 8px',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px',
          }}
        >
          {chatMessages.length === 0 && (
            <p style={{ color: 'var(--muted)', fontSize: '13px', textAlign: 'center', marginTop: '16px' }}>
              Start a conversation...
            </p>
          )}
          {chatMessages.map((msg, i) => (
            <div
              key={i}
              style={{
                maxWidth: '72%',
                alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                padding: '11px 12px',
                borderRadius: '18px',
                fontSize: '13px',
                lineHeight: 1.55,
                border: '1px solid rgba(21,29,25,0.06)',
                boxShadow: '0 10px 20px rgba(24,30,27,0.04)',
                background:
                  msg.role === 'user'
                    ? 'linear-gradient(180deg, rgba(181,206,184,0.26), rgba(255,255,255,0.56))'
                    : 'rgba(255,255,255,0.66)',
              }}
            >
              <span
                style={{
                  display: 'block',
                  fontSize: '11px',
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  color: 'var(--muted-2)',
                  marginBottom: '6px',
                }}
              >
                {msg.role === 'user' ? 'You' : 'DayPilot'}
              </span>
              {msg.role === 'user' ? (
                msg.text
              ) : (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p style={{ margin: '0 0 4px', lineHeight: 1.55 }}>{children}</p>,
                    ul: ({ children }) => <ul style={{ margin: '3px 0', paddingLeft: '16px' }}>{children}</ul>,
                    ol: ({ children }) => <ol style={{ margin: '3px 0', paddingLeft: '16px' }}>{children}</ol>,
                    li: ({ children }) => <li style={{ marginBottom: '2px' }}>{children}</li>,
                    strong: ({ children }) => <strong style={{ fontWeight: 700 }}>{children}</strong>,
                    code: ({ children }) => <code style={{ background: 'rgba(21,29,25,0.07)', borderRadius: '4px', padding: '1px 4px', fontSize: '11px', fontFamily: 'monospace' }}>{children}</code>,
                  }}
                >
                  {msg.text}
                </ReactMarkdown>
              )}
            </div>
          ))}
          {sending && (
            <div
              style={{
                alignSelf: 'flex-start',
                color: 'var(--muted)',
                fontSize: '12px',
                fontStyle: 'italic',
                padding: '8px 12px',
              }}
            >
              DayPilot is responding...
            </div>
          )}
        </div>

        {/* compose */}
        <div
          style={{
            padding: '14px 16px 16px',
            borderTop: '1px solid rgba(21,29,25,0.06)',
            background: 'linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.34))',
          }}
        >
          <div
            style={{
              borderRadius: '22px',
              border: '1px solid rgba(255,255,255,0.72)',
              background: 'linear-gradient(180deg, rgba(255,255,255,0.68), rgba(255,255,255,0.44))',
              boxShadow: '0 18px 38px rgba(24,30,27,0.06)',
              padding: '10px',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              backdropFilter: 'blur(18px) saturate(130%)',
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && send()}
              placeholder="Ask DayPilot to replan, explain, or summarize..."
              style={{
                flex: 1,
                border: 0,
                outline: 'none',
                background: 'transparent',
                color: 'var(--text)',
                fontSize: '13px',
                letterSpacing: '0.01em',
              }}
            />
            <button
              onClick={send}
              disabled={sending || !input.trim()}
              style={{
                width: '42px',
                height: '42px',
                borderRadius: '16px',
                border: 0,
                background: 'linear-gradient(135deg, #161d1b, #36423c)',
                color: 'white',
                boxShadow: '0 12px 24px rgba(24,30,27,0.16)',
                cursor: 'pointer',
                display: 'grid',
                placeItems: 'center',
                fontSize: '16px',
                flexShrink: 0,
                opacity: sending || !input.trim() ? 0.5 : 1,
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
