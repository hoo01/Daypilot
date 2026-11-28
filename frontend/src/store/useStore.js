import { create } from 'zustand';
import { api } from '../utils/api';
import { storage } from '../utils/storage';

export const useStore = create((set, get) => ({
  tasks: [],
  noSchedule: false,
  chatMessages: [],
  isBackendDown: false,
  isSending: false,
  // Hand-off from AgentDrawer to ChatPage: { date, proposal } taken from a DayPlan.
  pendingProposal: null,
  // Last DayPlan version seen per date — lets components tell when state changed.
  planVersions: {},

  setTasks: (tasks) => set({ tasks }),
  setNoSchedule: (v) => set({ noSchedule: v }),
  setIsBackendDown: (v) => set({ isBackendDown: v }),
  setIsSending: (v) => set({ isSending: v }),
  setPendingProposal: (p) => set({ pendingProposal: p }),

  // Record a DayPlan from the server; returns true if its version differs from the last one seen.
  noteDayPlan: (dayPlan) => {
    if (!dayPlan?.date) return false;
    const prev = get().planVersions[dayPlan.date];
    set({ planVersions: { ...get().planVersions, [dayPlan.date]: dayPlan.version } });
    return prev !== dayPlan.version;
  },

  addMessage: (msg) =>
    set((state) => ({ chatMessages: [...state.chatMessages, msg] })),
  setMessages: (msgs) => set({ chatMessages: msgs }),

  refreshSchedule: async (userId) => {
    try {
      const res    = await api.getScheduleToday(userId);
      const list   = Array.isArray(res) ? res : res.tasks || [];
      const sorted = list.sort((a, b) => (a.start_time || '').localeCompare(b.start_time || ''));
      set({ tasks: sorted, noSchedule: false });
      storage.setTodaySchedule(sorted);
    } catch (err) {
      if (err?.status === 404) {
        set({ tasks: [], noSchedule: true });
        storage.setTodaySchedule(null);
      } else if (!get().tasks.length) {
        set({ noSchedule: true });
      }
    }
  },
}));
