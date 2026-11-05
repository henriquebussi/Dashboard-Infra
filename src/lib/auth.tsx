import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

export type AuthUser = {
  email: string;
  name: string;
};

type AuthContextValue = {
  user: AuthUser | null;
  signIn: (email: string, remember?: boolean) => void;
  signOut: () => void;
};

const STORAGE_KEY = 'sb100.auth';

function displayNameFromEmail(email: string) {
  const localPart = email.split('@')[0] ?? 'User';
  return localPart
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function readStoredUser(): AuthUser | null {
  if (typeof window === 'undefined') return null;

  try {
    const raw =
      window.localStorage.getItem(STORAGE_KEY) ??
      window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    const parsed = JSON.parse(raw) as Partial<AuthUser>;
    if (!parsed.email || typeof parsed.email !== 'string') return null;

    return {
      email: parsed.email,
      name:
        typeof parsed.name === 'string' && parsed.name.trim()
          ? parsed.name
          : displayNameFromEmail(parsed.email),
    };
  } catch {
    return null;
  }
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => readStoredUser());

  const signIn = useCallback((email: string, remember = true) => {
    const nextUser = { email, name: displayNameFromEmail(email) };
    const payload = JSON.stringify(nextUser);

    try {
      window.localStorage.removeItem(STORAGE_KEY);
      window.sessionStorage.removeItem(STORAGE_KEY);
      (remember ? window.localStorage : window.sessionStorage).setItem(
        STORAGE_KEY,
        payload,
      );
    } catch {
      // Storage can be unavailable in private browsing; keep the session in memory.
    }

    setUser(nextUser);
  }, []);

  const signOut = useCallback(() => {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
      window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // Nothing else to clear if storage is blocked.
    }
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, signIn, signOut }),
    [user, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside an AuthProvider');
  }
  return context;
}
