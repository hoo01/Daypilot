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
  const { chatMessages, addMessage, refreshSchedule, isSending, setIsSending } = useStore();
  const [loadingStep, setLoadingStep]   = useState(0);
  const [pendingProposal, setPendingProposal] = useState(null);
  const [selectedStrategy, setSelectedStrategy] = useState(null);
  const [proposalInput, setProposalInput]     = useState('');
  const [confirming, setConfirming]     = useState(false);
  const [scheduleToast, setScheduleToast]     = useState(null);
  const scrollRef    = useRef(null);
  const triggeredRef = useRef(false);
  const toastTimerRef = useRef(null);
  const inputRef     = useRef(null);

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
  }, [chatMessages, isSending]);

  useEffect(() => { return () => clearTimeout(toastTimerRef.current); }, []);

  function showToast(message) {
    setScheduleToast(message);
    clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setScheduleToast(null), 3500);
  }

  useEffect(() => {
    const trigger = searchParams.get('trigger');
    if (trigger === 'feedback' && !triggeredRef.current) {
      triggeredRef.current = true;
      navigate('/chat', { replace: true });
      sendMessage(FEEDBACK_TRIGGER_MSG);
    }
    if (trigger === 'proactive' && !triggeredRef.current) {
      triggeredRef.current = true;
      navigate('/chat', { replace: true });
      setIsSending(true);
      setTimeout(() => {
        setIsSending(false);
        addMessage({
          role: 'agent',
          text: "Looks like you're still home — did dinner with Mia get rescheduled? Want me to find another time this week?",
        });
      }, 2200);
    }
  }, []);

  const AFFIRM_RE = /^(yes|yeah|yep|yup|ok|okay|sure|confirm|go ahead|do it|sounds good|great|perfect|let'?s do it|y)\s*[!.]?$/i;

  async function sendMessage(text) {
    if (!text || isSending) return;

    // When a proposal is waiting and the user affirms, confirm directly instead of re-asking the LLM
    if (pendingProposal && AFFIRM_RE.test(text.trim())) {
      addMessage({ role: 'user', text });
      await handleConfirm();
      return;
    }

    const userId    = storage.getUserId();
    const sessionId = storage.getSessionId();
    addMessage({ role: 'user', text });
    setIsSending(true);
    setPendingProposal(null);
    try {
      const res = await api.chat(userId, text, sessionId);
      if (!sessionId && res.session_id) storage.setSessionId(res.session_id);
      addMessage({ role: 'agent', text: res.reply });
      if (res.pending_proposal) {
        setPendingProposal(res.pending_proposal);
        setSelectedStrategy(res.pending_proposal.data?.top_recommendation || null);
      }
      if (res.schedule_updated) refreshSchedule(userId);
    } catch {
      addMessage({ role: 'agent', text: 'Sorry, something went wrong. Please try again.' });
    } finally {
      setIsSending(false);
    }
  }

  async function handleSend() {
    const text = inputRef.current?.value.trim();
    if (!text) return;
    inputRef.current.value = '';
    await sendMessage(text);
  }

  async function handleConfirm() {
    if (!pendingProposal) return;
    const userId = storage.getUserId();
    setConfirming(true);
    const effectiveStrategy = selectedStrategy || pendingProposal.data?.top_recommendation;
    const proposalData = effectiveStrategy && pendingProposal.data?.strategies
      ? { ...pendingProposal.data, top_recommendation: effectiveStrategy }
      : pendingProposal.data;
    try {
      await api.confirmSchedule(
        userId,
        pendingProposal.date || new Date().toISOString().slice(0, 10),
        proposalData,
        pendingProposal.type,
      );
      await refreshSchedule(userId);
      showToast('Schedule updated for today');
    } catch {
      showToast('Could not save schedule — please try again.');
    } finally {
      setConfirming(false);
      setPendingProposal(null);
      setSelectedStrategy(null);
      setProposalInput('');
    }
  }

  function handleCancel() {
    setPendingProposal(null);
    setSelectedStrategy(null);
    setProposalInput('');
  }

  async function handleProposalModify() {
    const text = proposalInput.trim();
    if (!text) return;
    setProposalInput('');
    await sendMessage(text);
  }

  const dateLabel = new Intl.DateTimeFormat('en-US', {
    weekday: 'long', month: 'long', day: 'numeric',
  }).format(new Date());

  return (
    <div
      className="floating-panel"
      style={{
        height: '100%',
        borderRadius: 'var(--radius-xl)',
        background: 'rgba(255,255,255,0.06)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {/* toast */}
      {scheduleToast && (
        <div
          style={{
            position: 'absolute', top: '16px', left: '50%', transform: 'translateX(-50%)',
            zIndex: 600,
            background: 'rgba(10,8,30,0.92)',
            backdropFilter: 'blur(16px)',
            borderRadius: '999px',
            border: '1px solid rgba(255,255,255,0.14)',
            padding: '8px 18px',
            display: 'flex', alignItems: 'center', gap: '10px',
            whiteSpace: 'nowrap',
            boxShadow: '0 8px 32px rgba(0,0,0,0.32)',
          }}
        >
          <span style={{ fontSize: '13px', color: 'var(--accent)', fontWeight: 600 }}>
            ◆ {scheduleToast}
          </span>
          <button
            onClick={() => setScheduleToast(null)}
            style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: '12px', cursor: 'pointer', padding: 0, lineHeight: 1 }}
          >
            ✕
          </button>
        </div>
      )}

      {/* header */}
      <div
        style={{
          padding: '20px 24px 16px',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          flexShrink: 0,
        }}
      >
        <div style={{ fontSize: '11px', letterSpacing: '0.16em', textTransform: 'uppercase', color: 'var(--muted-2)', marginBottom: '4px' }}>
          DayPilot Chat
        </div>
        <h1 style={{ margin: 0, fontSize: '22px', fontWeight: 700, letterSpacing: '-0.04em', color: '#fff' }}>
          {dateLabel}
        </h1>
      </div>

      {/* messages */}
      <div
        ref={scrollRef}
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: '12px' }}
      >
        {chatMessages.length === 0 && !isSending && (
          <div style={{ textAlign: 'center', marginTop: '60px' }}>
            <div style={{ fontSize: '32px', marginBottom: '12px', opacity: 0.35 }}>◆</div>
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
                padding: '12px 16px',
                borderRadius: '18px',
                fontSize: '14px',
                lineHeight: 1.6,
                border: '1px solid rgba(255,255,255,0.10)',
                background:
                  msg.role === 'user'
                    ? 'rgba(255,255,255,0.12)'
                    : 'rgba(255,255,255,0.06)',
                color: '#fff',
              }}
            >
              <span style={{
                display: 'block',
                fontSize: '11px',
                letterSpacing: '0.10em',
                textTransform: 'uppercase',
                color: msg.role === 'user' ? 'var(--muted-2)' : 'var(--accent)',
                marginBottom: '6px',
                fontWeight: 600,
              }}>
                {msg.role === 'user' ? 'You' : '◆ DayPilot'}
              </span>
              <span style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</span>
            </div>
          </div>
        ))}

        {isSending && (
          <div
            className="thinking-bubble"
            style={{
              alignSelf: 'flex-start',
              padding: '12px 16px',
              borderRadius: '18px',
              border: '1px solid rgba(110,231,183,0.18)',
              background: 'rgba(110,231,183,0.06)',
              fontSize: '13px',
            }}
          >
            <span style={{ display: 'block', fontSize: '11px', letterSpacing: '0.10em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: '8px', fontWeight: 600 }}>
              ◆ DayPilot
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.55)', fontStyle: 'italic', transition: 'opacity 400ms ease' }}>
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

      {/* proposal bar */}
      {pendingProposal && (
        <div
          style={{
            borderTop: '1px solid rgba(255,255,255,0.08)',
            padding: '12px 16px',
            background: 'rgba(110,231,183,0.05)',
            flexShrink: 0,
          }}
        >
          <div style={{ fontSize: '11px', letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: '10px', fontWeight: 600 }}>
            ◆ Schedule Proposal
          </div>

          {/* Strategy selector — shown when the proposal has multiple options */}
          {pendingProposal.data?.strategies?.length > 1 && (
            <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', flexWrap: 'wrap' }}>
              {pendingProposal.data.strategies.map((s) => {
                const isSelected = (selectedStrategy || pendingProposal.data.top_recommendation) === s.name;
                const isRecommended = pendingProposal.data.top_recommendation === s.name;
                return (
                  <button
                    key={s.name}
                    onClick={() => setSelectedStrategy(s.name)}
                    style={{
                      padding: '7px 14px',
                      borderRadius: '10px',
                      border: isSelected
                        ? '1px solid rgba(110,231,183,0.55)'
                        : '1px solid rgba(255,255,255,0.12)',
                      background: isSelected
                        ? 'rgba(110,231,183,0.16)'
                        : 'rgba(255,255,255,0.05)',
                      color: isSelected ? 'var(--accent)' : 'var(--muted)',
                      fontSize: '12px',
                      fontWeight: isSelected ? 700 : 400,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '5px',
                      transition: '120ms ease',
                    }}
                  >
                    {s.name}
                    {isRecommended && (
                      <span style={{
                        fontSize: '10px',
                        padding: '1px 5px',
                        borderRadius: '6px',
                        background: 'rgba(110,231,183,0.18)',
                        color: 'var(--accent)',
                        fontWeight: 700,
                        letterSpacing: '0.06em',
                      }}>
                        TOP
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <input
              value={proposalInput}
              onChange={(e) => setProposalInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleProposalModify()}
              placeholder="Add requirements or modify the plan..."
              style={{
                flex: 1,
                border: '1px solid rgba(255,255,255,0.14)',
                borderRadius: '12px',
                padding: '9px 14px',
                background: 'rgba(255,255,255,0.07)',
                fontSize: '13px',
                color: '#fff',
                outline: 'none',
              }}
            />
            <button
              onClick={handleConfirm}
              disabled={confirming}
              style={{
                padding: '9px 20px',
                borderRadius: '12px',
                border: '1px solid rgba(110,231,183,0.35)',
                background: 'rgba(110,231,183,0.14)',
                color: 'var(--accent)',
                fontSize: '13px',
                fontWeight: 700,
                cursor: confirming ? 'not-allowed' : 'pointer',
                opacity: confirming ? 0.55 : 1,
                whiteSpace: 'nowrap', flexShrink: 0,
              }}
            >
              {confirming ? 'Saving…' : `Confirm${selectedStrategy ? ` "${selectedStrategy}"` : ''}`}
            </button>
            <button
              onClick={handleCancel}
              style={{
                padding: '9px 14px', borderRadius: '12px',
                border: '1px solid rgba(255,255,255,0.12)',
                background: 'transparent', color: 'var(--muted)',
                fontSize: '13px', cursor: 'pointer',
                whiteSpace: 'nowrap', flexShrink: 0,
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* compose */}
      <div
        style={{
          padding: '14px 16px 16px',
          background: 'rgba(255,255,255,0.03)',
          borderTop: '1px solid rgba(255,255,255,0.08)',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            borderRadius: '22px',
            border: '1px solid rgba(255,255,255,0.14)',
            background: 'rgba(255,255,255,0.07)',
            padding: '12px',
            display: 'flex', alignItems: 'center', gap: '12px',
          }}
        >
          <input
            ref={inputRef}
            defaultValue=""
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
            placeholder="Ask DayPilot to replan, explain, or summarize..."
            style={{
              flex: 1, border: 0, outline: 'none',
              background: 'transparent', color: '#fff',
              fontSize: '14px', letterSpacing: '0.01em',
            }}
          />
          <button
            onClick={handleSend}
            disabled={isSending}
            style={{
              width: '42px', height: '42px', borderRadius: '16px',
              border: '1px solid rgba(110,231,183,0.30)',
              background: 'rgba(110,231,183,0.14)',
              color: 'var(--accent)',
              cursor: 'pointer',
              display: 'grid', placeItems: 'center', fontSize: '16px', flexShrink: 0,
              opacity: isSending ? 0.4 : 1,
              transition: '160ms ease',
            }}
          >
            ↑
          </button>
        </div>
        <p style={{ marginTop: '8px', fontSize: '11px', color: 'var(--muted-2)', textAlign: 'center' }}>
          Press Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
