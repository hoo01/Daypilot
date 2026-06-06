import { create } from 'zustand';

export const useStore = create((set) => ({
  tasks: [],
  chatMessages: [],
  isBackendDown: false,

  setTasks: (tasks) => set({ tasks }),
  setIsBackendDown: (v) => set({ isBackendDown: v }),

  addMessage: (msg) =>
    set((state) => ({ chatMessages: [...state.chatMessages, msg] })),
  setMessages: (msgs) => set({ chatMessages: msgs }),
}));
