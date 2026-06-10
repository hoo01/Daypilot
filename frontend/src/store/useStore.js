import { create } from 'zustand';
import { api } from '../utils/api';
import { storage } from '../utils/storage';

export const useStore = create((set, get) => ({
  tasks: [],
  noSchedule: false,
  chatMessages: [],
  isBackendDown: false,
  isSending: false,

  setTasks: (tasks) => set({ tasks }),
  setNoSchedule: (v) => set({ noSchedule: v }),
  setIsBackendDown: (v) => set({ isBackendDown: v }),
  setIsSending: (v) => set({ isSending: v }),

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
