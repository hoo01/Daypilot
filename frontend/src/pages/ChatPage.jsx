import { useEffect, useState, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useStore } from '../store/useStore';
import { api } from '../utils/api';
import { storage } from '../utils/storage';

const FEEDBACK_TRIGGER_MSG =
  "I just submitted today's progress. What do you suggest for rescheduling?";

// ─── Strategy visual config ───────────────────────────────────────────────
const STRATEGY_CONFIG = {
  'Fastest': {
    color: '#f59e0b',
    bg: 'rgba(245,158,11,0.08)',
    border: 'rgba(245,158,11,0.22)',
    selectedBorder: 'rgba(245,158,11,0.55)',
    selectedBg: 'rgba(245,158,11,0.13)',
    btnBg: 'rgba(245,158,11,0.14)',
    icon: 'lightning',
    baseClass: 'strat-base-amber',
    glowClass: 'strat-card-selected-amber',
  },
  'Most Productive': {
    color: '#6ee7b7',
    bg: 'rgba(110,231,183,0.06)',
    border: 'rgba(110,231,183,0.20)',
    selectedBorder: 'rgba(110,231,183,0.55)',
    selectedBg: 'rgba(110,231,183,0.11)',
    btnBg: 'rgba(110,231,183,0.14)',
    icon: 'target',
    baseClass: 'strat-base-green',
    glowClass: 'strat-card-selected-green',
  },
  'Most Relaxed': {
    color: '#a78bfa',
    bg: 'rgba(167,139,250,0.06)',
    border: 'rgba(167,139,250,0.20)',
    selectedBorder: 'rgba(167,139,250,0.55)',
    selectedBg: 'rgba(167,139,250,0.11)',
    btnBg: 'rgba(167,139,250,0.14)',
    icon: 'smile',
    baseClass: 'strat-base-purple',
    glowClass: 'strat-card-selected-purple',
  },
};

function getStratCfg(name) {
  return STRATEGY_CONFIG[name] || STRATEGY_CONFIG['Most Productive'];
}

function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.getHours()}:${d.getMinutes().toString().padStart(2, '0')}`;
}

function fmtHours(h) {
  if (!h) return '—';
  const hrs = Math.floor(h);
  const mins = Math.round((h - hrs) * 60);
  if (!hrs) return `${mins}m`;
  if (!mins) return `${hrs}h`;
  return `${hrs}h ${mins}m`;
}

function taskTone(type) {
  const map = {
    deep_work: { bg: 'rgba(110,231,183,0.16)', color: '#6ee7b7' },
    break:     { bg: 'rgba(167,139,250,0.16)', color: '#a78bfa' },
    health:    { bg: 'rgba(251,146,60,0.16)',  color: '#fb923c' },
    social:    { bg: 'rgba(248,113,113,0.16)', color: '#f87171' },
    class:     { bg: 'rgba(96,165,250,0.16)',  color: '#60a5fa' },
  };
  return map[type] || { bg: 'rgba(255,255,255,0.10)', color: 'rgba(255,255,255,0.58)' };
}

// ─── Inline SVG icons (no emoji, themed) ─────────────────────────────────
function Icon({ type, size = 14, color = 'currentColor' }) {
  const s = { display: 'block', flexShrink: 0 };
  if (type === 'lightning') return (
    <svg style={s} width={size} height={size} viewBox="0 0 16 16" fill={color}>
      <path d="M9.5 1.5L3.5 9h5l-2 5.5L13.5 7H8.5L9.5 1.5z"/>
    </svg>
  );
  if (type === 'target') return (
    <svg style={s} width={size} height={size} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6.5" stroke={color} strokeWidth="1.4"/>
      <circle cx="8" cy="8" r="3.5" stroke={color} strokeWidth="1.4"/>
      <circle cx="8" cy="8" r="1.5" fill={color}/>
    </svg>
  );
  if (type === 'smile') return (
    <svg style={s} width={size} height={size} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6.5" stroke={color} strokeWidth="1.4"/>
      <path d="M5.5 9.5c.5 1 1.4 1.5 2.5 1.5s2-.5 2.5-1.5" stroke={color} strokeWidth="1.4" strokeLinecap="round"/>
      <circle cx="5.8" cy="7" r="0.9" fill={color}/>
      <circle cx="10.2" cy="7" r="0.9" fill={color}/>
    </svg>
  );
  if (type === 'check') return (
    <svg style={s} width={size} height={size} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6.5" stroke={color} strokeWidth="1.4"/>
      <path d="M5.5 8l2 2 3-3.5" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
  return null;
}

// ─── Main component ───────────────────────────────────────────────────────
export default function ChatPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { chatMessages, addMessage, refreshSchedule, isSending, setIsSending } = useStore();
  const [loadingStep, setLoadingStep]       = useState(0);
  const [pendingProposal, setPendingProposal] = useState(null);
  const [selectedStrategy, setSelectedStrategy] = useState(null);
  const [proposalInput, setProposalInput]   = useState('');
  const [confirming, setConfirming]         = useState(false);
  const [scheduleToast, setScheduleToast]   = useState(null);
  const [toastKey, setToastKey]             = useState(0);
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
    setToastKey((k) => k + 1);
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

  // strategyName: optional — when called from "Choose Plan" buttons on panels
  async function handleConfirm(strategyName) {
    if (!pendingProposal || confirming) return;
    const userId = storage.getUserId();
    const effectiveStrategy = strategyName || selectedStrategy || pendingProposal.data?.top_recommendation;
    if (strategyName) setSelectedStrategy(strategyName);
    setConfirming(true);
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
      storage.setLastFeedbackDate(null);
      showToast('Schedule updated for today');
      // Fixed confirmation message — no LLM call needed
      const label = effectiveStrategy || 'your new';
      addMessage({
        role: 'agent',
        text: `Done — the **${label}** plan is locked in for today. Head to **Today** to see your updated schedule.`,
      });
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

  const strategies = pendingProposal?.data?.strategies;
  const isMultiStrategy = strategies?.length > 1;

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
      {/* ── Toast: slides up from below, auto-fades ──────────────── */}
      {scheduleToast && (
        <div
          key={toastKey}
          className="toast-up"
          style={{
            position: 'absolute',
            top: '20px',
            left: '50%',
            zIndex: 600,
            background: 'rgba(10,8,30,0.92)',
            backdropFilter: 'blur(18px)',
            borderRadius: '999px',
            border: '1px solid rgba(110,231,183,0.28)',
            padding: '7px 16px 7px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            whiteSpace: 'nowrap',
            boxShadow: '0 8px 32px rgba(0,0,0,0.36), 0 0 0 1px rgba(110,231,183,0.12)',
          }}
        >
          <Icon type="check" size={15} color="var(--accent)" />
          <span style={{ fontSize: '13px', color: 'var(--accent)', fontWeight: 600 }}>
            {scheduleToast}
          </span>
        </div>
      )}

      {/* ── Header ───────────────────────────────────────────────── */}
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
        <h1 style={{ margin: 0, fontSize: '22px', fontWeight: 700, letterSpacing: '0.04em', color: '#fff' }}>
          {dateLabel}
        </h1>
      </div>

      {/* ── Messages ─────────────────────────────────────────────── */}
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
              className="msg-bubble"
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

      {/* ── Proposal section ─────────────────────────────────────── */}
      {pendingProposal && (
        <div
          style={{
            borderTop: '1px solid rgba(255,255,255,0.08)',
            padding: '16px 18px',
            background: 'rgba(7,5,26,0.60)',
            backdropFilter: 'blur(20px) saturate(160%)',
            flexShrink: 0,
          }}
        >
          {/* Section label */}
          <div style={{
            fontSize: '10px',
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: 'var(--muted-2)',
            marginBottom: '12px',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}>
            <span style={{ color: 'var(--accent)', opacity: 0.7 }}>◆</span>
            Schedule Proposal
          </div>

          {/* ── 3-panel grid ────────────────────────────────────── */}
          {isMultiStrategy ? (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '10px',
              marginBottom: '12px',
            }}>
              {strategies.map((s) => {
                const cfg = getStratCfg(s.name);
                const isSelected = (selectedStrategy || pendingProposal.data?.top_recommendation) === s.name;
                const isRecommended = pendingProposal.data?.top_recommendation === s.name;
                const isConfirmingThis = confirming && (selectedStrategy === s.name || (!selectedStrategy && isRecommended));

                return (
                  <div
                    key={s.name}
                    onClick={() => setSelectedStrategy(s.name)}
                    className={`${cfg.baseClass}${isSelected ? ` ${cfg.glowClass}` : ''}`}
                    style={{
                      borderRadius: '16px',
                      border: `1px solid ${isSelected ? cfg.selectedBorder : cfg.border}`,
                      background: isSelected ? cfg.selectedBg : cfg.bg,
                      backdropFilter: 'blur(16px) saturate(160%)',
                      WebkitBackdropFilter: 'blur(16px) saturate(160%)',
                      padding: '14px 14px 12px',
                      cursor: 'pointer',
                      transition: 'border-color 160ms ease, background 160ms ease',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                    }}
                  >
                    {/* Panel header */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '7px', minHeight: '20px' }}>
                      <Icon type={cfg.icon} size={16} color={cfg.color} />
                      <span style={{
                        fontSize: '14px',
                        fontWeight: 700,
                        color: cfg.color,
                        letterSpacing: '0.01em',
                      }}>
                        {s.name}
                      </span>
                      {isRecommended && (
                        <span style={{
                          marginLeft: 'auto',
                          fontSize: '8px',
                          padding: '1px 6px',
                          borderRadius: '999px',
                          background: cfg.selectedBg,
                          color: cfg.color,
                          fontWeight: 700,
                          letterSpacing: '0.08em',
                          border: `1px solid ${cfg.border}`,
                          whiteSpace: 'nowrap',
                        }}>
                          TOP
                        </span>
                      )}
                    </div>

                    {/* Description */}
                    {s.description && (
                      <p style={{
                        fontSize: '11px',
                        color: 'var(--muted)',
                        margin: 0,
                        lineHeight: 1.45,
                      }}>
                        {s.description}
                      </p>
                    )}

                    {/* Total time */}
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                      <span style={{ fontSize: '15px', fontWeight: 700, color: cfg.color, letterSpacing: '-0.02em' }}>
                        {fmtHours(s.total_focus_hours)}
                      </span>
                      <span style={{ fontSize: '11px', color: 'var(--muted-2)' }}>scheduled</span>
                    </div>

                    {/* Task list */}
                    <div style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '3px',
                      maxHeight: '130px',
                      overflowY: 'auto',
                    }}>
                      {s.tasks?.map((task, ti) => {
                        const tone = taskTone(task.type);
                        return (
                          <div key={ti} style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                            fontSize: '11px',
                          }}>
                            <span style={{
                              color: 'var(--muted-2)',
                              fontVariantNumeric: 'tabular-nums',
                              minWidth: '32px',
                              flexShrink: 0,
                            }}>
                              {fmtTime(task.start_time)}
                            </span>
                            <span style={{
                              padding: '2px 7px',
                              borderRadius: '5px',
                              background: tone.bg,
                              color: tone.color,
                              fontWeight: 500,
                              whiteSpace: 'nowrap',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              maxWidth: '100%',
                            }}>
                              {task.title}
                            </span>
                          </div>
                        );
                      })}
                    </div>

                    {/* Choose Plan button */}
                    <button
                      onClick={(e) => { e.stopPropagation(); handleConfirm(s.name); }}
                      disabled={confirming}
                      className="choose-plan-btn"
                      style={{
                        marginTop: '2px',
                        padding: '8px 0',
                        borderRadius: '10px',
                        border: `1px solid ${isSelected ? cfg.selectedBorder : cfg.border}`,
                        background: isSelected ? cfg.btnBg : 'rgba(255,255,255,0.04)',
                        color: cfg.color,
                        fontSize: '12px',
                        fontWeight: 700,
                        cursor: confirming ? 'not-allowed' : 'pointer',
                        opacity: confirming ? 0.55 : 1,
                        width: '100%',
                        letterSpacing: '0.01em',
                      }}
                    >
                      {isConfirmingThis ? 'Saving…' : 'Choose Plan'}
                    </button>
                  </div>
                );
              })}
            </div>
          ) : (
            /* Single-strategy fallback: original pill buttons */
            <div style={{ display: 'flex', gap: '8px', marginBottom: '10px', flexWrap: 'wrap' }}>
              {(pendingProposal.data?.strategies || []).map((s) => {
                const isSelected = (selectedStrategy || pendingProposal.data?.top_recommendation) === s.name;
                const isRecommended = pendingProposal.data?.top_recommendation === s.name;
                return (
                  <button
                    key={s.name}
                    onClick={() => setSelectedStrategy(s.name)}
                    style={{
                      padding: '7px 14px',
                      borderRadius: '10px',
                      border: isSelected ? '1px solid rgba(110,231,183,0.55)' : '1px solid rgba(255,255,255,0.12)',
                      background: isSelected ? 'rgba(110,231,183,0.16)' : 'rgba(255,255,255,0.05)',
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

          {/* Modify input + actions */}
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <input
              value={proposalInput}
              onChange={(e) => setProposalInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleProposalModify()}
              placeholder="Ask to adjust, add requirements, or modify…"
              className="proposal-input"
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
            {/* Show global Confirm only when it's a single strategy */}
            {!isMultiStrategy && (
              <button
                onClick={() => handleConfirm()}
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
                  whiteSpace: 'nowrap',
                  flexShrink: 0,
                }}
              >
                {confirming ? 'Saving…' : `Confirm${selectedStrategy ? ` "${selectedStrategy}"` : ''}`}
              </button>
            )}
            <button
              onClick={handleCancel}
              className="cancel-btn"
              style={{
                padding: '9px 14px',
                borderRadius: '12px',
                border: '1px solid rgba(255,255,255,0.12)',
                background: 'transparent',
                color: 'var(--muted)',
                fontSize: '13px',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ── Compose ──────────────────────────────────────────────── */}
      <div
        style={{
          padding: '14px 16px 16px',
          background: 'rgba(255,255,255,0.03)',
          borderTop: '1px solid rgba(255,255,255,0.08)',
          flexShrink: 0,
        }}
      >
        <div
          className="compose-area"
          style={{
            borderRadius: '22px',
            border: '1px solid rgba(255,255,255,0.14)',
            background: 'rgba(255,255,255,0.07)',
            padding: '12px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          <input
            ref={inputRef}
            defaultValue=""
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
            placeholder="Ask DayPilot to replan, explain, or summarize..."
            style={{
              flex: 1,
              border: 0,
              outline: 'none',
              background: 'transparent',
              color: '#fff',
              fontSize: '14px',
              letterSpacing: '0.01em',
            }}
          />
          <button
            onClick={handleSend}
            disabled={isSending}
            style={{
              width: '42px',
              height: '42px',
              borderRadius: '16px',
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
