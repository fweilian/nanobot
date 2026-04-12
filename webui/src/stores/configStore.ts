import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ConfigState {
  apiUrl: string;
  apiKey: string;
  theme: 'light' | 'dark';
  setApiUrl: (url: string) => void;
  setApiKey: (key: string) => void;
  setTheme: (theme: 'light' | 'dark') => void;
}

export const useConfigStore = create<ConfigState>()(
  persist(
    (set) => ({
      apiUrl: 'http://localhost:8890',
      apiKey: '',
      theme: 'light',
      setApiUrl: (url) => set({ apiUrl: url }),
      setApiKey: (key) => set({ apiKey: key }),
      setTheme: (theme) => set({ theme }),
    }),
    { name: 'nanobot-config' }
  )
);
