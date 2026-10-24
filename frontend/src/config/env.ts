/**
 * Frontend environment configuration.
 * Strictly typed with fallback defaults for local development.
 */

export interface AppConfig {
  apiBaseUrl: string;
  appName: string;
  appVersion: string;
  isDev: boolean;
}

export const config: AppConfig = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
  appName: 'AI Video Clipper',
  appVersion: '0.2.1',
  isDev: import.meta.env.DEV,
};
