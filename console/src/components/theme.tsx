import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Theme = "dark" | "light";

type ThemeContextValue = {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
};

const STORAGE_KEY = "console.theme";
const META_THEME_SELECTOR = 'meta[name="theme-color"]';
const META_SCHEME_SELECTOR = 'meta[name="color-scheme"]';
const THEME_META: Record<Theme, { themeColor: string; colorScheme: string }> = {
  dark: { themeColor: "#0a0f14", colorScheme: "dark" },
  light: { themeColor: "#f7fafc", colorScheme: "light" },
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStoredTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const raw = window.localStorage.getItem(STORAGE_KEY);
  return raw === "light" ? "light" : "dark";
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.remove("dark", "light");
  root.classList.add(theme);

  const meta = THEME_META[theme];
  document.querySelector<HTMLMetaElement>(META_THEME_SELECTOR)?.setAttribute("content", meta.themeColor);
  document.querySelector<HTMLMetaElement>(META_SCHEME_SELECTOR)?.setAttribute("content", meta.colorScheme);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme());

  useEffect(() => {
    applyTheme(theme);
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      setTheme,
      toggleTheme: () => setTheme((current) => (current === "dark" ? "light" : "dark")),
    }),
    [theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context;
}
