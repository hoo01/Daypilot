import { useEffect, useState, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { api } from '../utils/api';
import { storage } from '../utils/storage';

const FEEDBACK_TRIGGER_MSG =
  "I just submitted today's progress. What do you suggest for rescheduling?";

export default function ChatPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { chatMessages, addMessage, setTasks } = useStore();
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const scrollRef = useRef(null);
  const triggeredRef = useRef(false);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatMessages, sending]);

  // auto-send trigger=feedback on mount
  useEffect(() => {
    const trigger = searchParams.get('trigger');
    if (trigger === 'feedback' && !triggeredRef.current) {
      triggeredRef.current = true;
      // strip param from URL
      navigate('/chat', { replace: true });
      sendMessage(FEEDBACK_TRIGGER_MSG);
    }
  }, []);

  async function sendMessage(text) {
    if (!text || sending) return;
    const userId = storage.getUserId();
    const sessionId = storage.getSessionId();
    addMessage({ role: 'user', text });
    setSending(true);
    try {
      const res = await api.chat(userId, text, sessionId);
      if (!sessionId && res.session_id) storage.setSessionId(res.session_id);
      addMessage({ role: 'agent', text: res.reply });

      // if agent updated the schedule, re-fetch
      if (res.schedule_updated) {
        try {
          const schedule = await api.getScheduleToday(userId);
          const list = Array.isArray(schedule) ? schedule : schedule.tasks || [];
          const sorted = list.sort((a, b) =>
            (a.start_time || '').localeCompare(b.start_time || '')
          );
          setTasks(sorted);
          storage.setTodaySchedule(sorted);
        } catch {
          // non-fatal
        }
      }
    } catch {
      addMessage({ role: 'agent', text: 'Sorry, something went wrong. Please try again.' });
    } finally {
      setSending(false);
    }
  }

  async function handleSend() {
    const text = input.trim();
    if (!text) return;
    setInput('');
    await sendMessage(text);
  }

  const dateLabel = new Intl.DateTimeFormat('en-US', {
    weekday: 'long', month: 'long', day: 'numeric',
  }).format(new Date());

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
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {/* header */}
      <div
        style={{
          padding: '20px 24px 16px',
          borderBottom: '1px solid var(--line)',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: '11px',
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--muted-2)',
            marginBottom: '4px',
          }}
        >
          DayPilot Chat
        </div>
        <h1
          style={{
            margin: 0,
            fontSize: '22px',
            fontWeight: 700,
            letterSpacing: '-0.05em',
          }}
        >
          {dateLabel}
        </h1>
      </div>

      {/* messages */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          padding: '20px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
        }}
      >
        {chatMessages.length === 0 && !sending && (
          <div
            style={{
              textAlign: 'center',
              marginTop: '60px',
            }}
          >
            <div style={{ fontSize: '32px', marginBottom: '12px' }}>◆</div>
            <p style={{ color: 'var(--muted)', fontSize: '14px', lineHeight: 1.6 }}>
              Ask DayPilot to plan, reschedule, or explain your day.
            </p>
          </div>
        )}

        {chatMessages.map((msg, i) => (
          <div
            key={i}
            style={{
              maxWidth: '72%',
              alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
            }}
          >
            <div
              style={{
                padding: '12px 14px',
                borderRadius: '18px',
                fontSize: '14px',
                lineHeight: 1.55,
                letterSpacing: '0.01em',
                border: '1px solid rgba(21,29,25,0.06)',
                boxShadow: '0 10px 20px rgba(24,30,27,0.04)',
                background:
                  msg.role === 'user'
                    ? 'linear-gradient(180deg, rgba(181,206,184,0.26), rgba(255,255,255,0.56))'
                    : 'rgba(255,255,255,0.72)',
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
              {msg.text}
            </div>
          </div>
        ))}

        {sending && (
          <div
            style={{
              alignSelf: 'flex-start',
              padding: '10px 14px',
              borderRadius: '18px',
              border: '1px solid rgba(21,29,25,0.06)',
              background: 'rgba(255,255,255,0.72)',
              fontSize: '13px',
              color: 'var(--muted)',
              fontStyle: 'italic',
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
              DayPilot
            </span>
            DayPilot is responding...
          </div>
        )}
      </div>

      {/* compose bar */}
      <div
        style={{
          padding: '14px 16px 16px',
          background:
            'linear-gradient(180deg, rgba(242,246,240,0), rgba(242,246,240,0.78) 18%, rgba(242,246,240,0.97))',
          borderTop: '1px solid rgba(21,29,25,0.05)',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            borderRadius: '22px',
            border: '1px solid rgba(255,255,255,0.72)',
            background: 'linear-gradient(180deg, rgba(255,255,255,0.66), rgba(255,255,255,0.42))',
            boxShadow: '0 18px 38px rgba(24,30,27,0.06)',
            padding: '12px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            backdropFilter: 'blur(18px) saturate(130%)',
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
            placeholder="Ask DayPilot to replan, explain, or summarize..."
            style={{
              flex: 1,
              border: 0,
              outline: 'none',
              background: 'transparent',
              color: 'var(--text)',
              fontSize: '14px',
              letterSpacing: '0.01em',
            }}
          />
          <button
            onClick={handleSend}
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
              transition: '160ms ease',
            }}
          >
            ↑
          </button>
        </div>
        <p
          style={{
            marginTop: '8px',
            fontSize: '11px',
            color: 'var(--muted)',
            textAlign: 'center',
          }}
        >
          Press Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
