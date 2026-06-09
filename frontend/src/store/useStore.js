import { create } from 'zustand';

export const useStore = create((set) => ({
  tasks: [],
  chatMessages: [],
  isBackendDown: false,
  isSending: false,

  setTasks: (tasks) => set({ tasks }),
  setIsBackendDown: (v) => set({ isBackendDown: v }),
  setIsSending: (v) => set({ isSending: v }),

  addMessage: (msg) =>
    set((state) => ({ chatMessages: [...state.chatMessages, msg] })),
  setMessages: (msgs) => set({ chatMessages: msgs }),
}));
