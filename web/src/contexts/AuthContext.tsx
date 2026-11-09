/**
 * SASAA – Authentication Context
 * Provides the current user, login, register, and logout functions to
 * the entire component tree. Components consume this via useAuth().
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { auth as authApi, users as usersApi, type UserProfile } from '../lib/api';
import { clearTokens, getAccessToken, getRefreshToken, isAuthenticated, saveTokens } from '../lib/auth';

interface AuthContextValue {
  user: UserProfile | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On mount, try to restore the session from stored token
  useEffect(() => {
    if (!isAuthenticated()) {
      setIsLoading(false);
      return;
    }
    usersApi
      .me()
      .then((profile) => setUser(profile))
      .catch(() => {
        // Token invalid or expired — clear it
        clearTokens();
      })
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await authApi.login(email, password);
    saveTokens(tokens.access_token, tokens.refresh_token);
    const profile = await usersApi.me();
    setUser(profile);
  }, []);

  const register = useCallback(
    async (email: string, password: string, fullName: string) => {
      const tokens = await authApi.register(email, password, fullName);
      saveTokens(tokens.access_token, tokens.refresh_token);
      const profile = await usersApi.me();
      setUser(profile);
    },
    [],
  );

  const logout = useCallback(async () => {
    const login = useCallback(async (email: string, password: string) => {
  console.log("1. Login started");
  console.log("2. Email:", email);

  try {
    const tokens = await authApi.login(email.trim(), password);

    console.log("3. Backend login successful");

    saveTokens(tokens.access_token, tokens.refresh_token);

    console.log("4. Tokens saved");

    const profile = await usersApi.me();

    console.log("5. User profile loaded");

    setUser(profile);
  } catch (error) {
    console.error("LOGIN FLOW FAILED:", error);
    throw error;
  }
}, []);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
