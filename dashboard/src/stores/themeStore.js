import { create } from 'zustand'
import { persist } from 'zustand/middleware'

const useThemeStore = create(
  persist(
    (set, get) => ({
      darkMode: false,
      toggleDarkMode: () => set((state) => ({ darkMode: !state.darkMode })),
      setDarkMode: (dark) => set({ darkMode: dark }),
    }),
    {
      name: 'agenticaiops-theme',
    }
  )
)

export default useThemeStore
