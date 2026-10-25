/**
 * Typed environment configuration for AI Animation Studio frontend.
 */

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1/animation';

// Strip trailing slash to guarantee clean URL concatenation
export const API_BASE_URL = rawBaseUrl.endsWith('/') ? rawBaseUrl.slice(0, -1) : rawBaseUrl;
