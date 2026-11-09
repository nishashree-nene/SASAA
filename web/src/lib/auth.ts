/**
 * SASAA – Token Management
 * Centralised token storage.
 * Access tokens are stored in sessionStorage (cleared when the tab closes)
 * with a localStorage fallback key so the user stays logged in across tabs.
 * Refresh tokens are never stored in JS-accessible storage in this MVP.
 */

const ACCESS_KEY = 'sasaa_access_token';
const REFRESH_KEY = 'sasaa_refresh_token';

export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_KEY) ?? localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return sessionStorage.getItem(REFRESH_KEY) ?? localStorage.getItem(REFRESH_KEY);
}

export function saveTokens(accessToken: string, refreshToken: string): void {
  // Save in both so tabs share the session
  localStorage.setItem(ACCESS_KEY, accessToken);
  localStorage.setItem(REFRESH_KEY, refreshToken);
  sessionStorage.setItem(ACCESS_KEY, accessToken);
  sessionStorage.setItem(REFRESH_KEY, refreshToken);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  sessionStorage.removeItem(ACCESS_KEY);
  sessionStorage.removeItem(REFRESH_KEY);
}

export function isAuthenticated(): boolean {
  return !!getAccessToken();
}
