const QUOTES = [
  "The best time to start was yesterday. The second best time is now.",
  "Energy is finite. Attention is the real currency.",
  "Rest is not idleness — it's maintenance.",
  "A clear schedule is a calm mind.",
  "One focused hour beats four scattered ones.",
  "Progress, not perfection.",
  "Your future self is watching how you spend today.",
  "Small wins compound quietly.",
  "Protect your mornings like a board meeting.",
  "Done is better than perfect, but good is better than rushed.",
  "Momentum is built one completed task at a time.",
  "The quality of your day determines the quality of your life.",
  "Subtract before you add.",
  "Sleep is the highest-leverage productivity tool.",
  "Boundaries are not walls — they're architecture.",
  "You can't pour from an empty calendar.",
  "Every no to the unimportant is a yes to what matters.",
  "Clarity precedes speed.",
  "Your habits are your hidden schedule.",
  "A rested mind sees further.",
  "Time you enjoy wasting is not wasted time.",
  "Consistency beats intensity in the long run.",
  "Today's preparation is tomorrow's advantage.",
  "The pause is part of the plan.",
  "What gets scheduled gets done.",
  "Focused work is a form of self-respect.",
  "Less on your plate means more on your mind.",
  "Routine is not boring — it's liberating.",
  "The cost of distraction is invisible until it isn't.",
  "End your day by designing the next one.",
];

export function getDailyQuote() {
  const start = new Date(new Date().getFullYear(), 0, 0);
  const diff = Date.now() - start.getTime();
  const dayOfYear = Math.floor(diff / (1000 * 60 * 60 * 24));
  return QUOTES[dayOfYear % QUOTES.length];
}
