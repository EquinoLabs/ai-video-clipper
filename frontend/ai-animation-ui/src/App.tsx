import { useEffect, useState } from 'react';
import { animationApi } from './lib/api/client';
import type { AnimationConfig, AnimationHealth } from './lib/api/types';
import './App.css';

export function App() {
  const [health, setHealth] = useState<AnimationHealth | null>(null);
  const [config, setConfig] = useState<AnimationConfig | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'brief' | 'script' | 'plan' | 'render'>('brief');

  useEffect(() => {
    let ignore = false;
    async function loadStatus() {
      setLoading(true);
      setError(null);
      try {
        const [h, c] = await Promise.all([
          animationApi.checkHealth(),
          animationApi.getConfig(),
        ]);
        if (!ignore) {
          setHealth(h);
          setConfig(c);
        }
      } catch (err: unknown) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : 'Failed to connect to Animation Studio API');
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    loadStatus();
    return () => {
      ignore = true;
    };
  }, []);

  return (
    <div className="animation-app">
      {/* Header */}
      <header className="animation-header">
        <div className="header-brand">
          <div className="brand-logo">🎨</div>
          <div>
            <h1 className="brand-title">AI Animation Studio</h1>
            <span className="brand-subtitle">Explainer Video & Animated Story Creation</span>
          </div>
        </div>

        <div className="header-status">
          {loading ? (
            <span className="status-badge connecting">Connecting...</span>
          ) : error ? (
            <span className="status-badge offline" title={error}>Backend Disconnected</span>
          ) : (
            <span className="status-badge online">
              ● API Online (v{health?.feature_version || '0.1.0'})
            </span>
          )}
        </div>
      </header>

      {/* Main Workspace Layout */}
      <div className="animation-container">
        {/* Navigation Tabs */}
        <nav className="pipeline-nav">
          <button
            type="button"
            className={`nav-item ${activeTab === 'brief' ? 'active' : ''}`}
            onClick={() => setActiveTab('brief')}
          >
            1. Brief & Outline
          </button>
          <button
            type="button"
            className={`nav-item ${activeTab === 'script' ? 'active' : ''}`}
            onClick={() => setActiveTab('script')}
          >
            2. Scriptwriter Chat
          </button>
          <button
            type="button"
            className={`nav-item ${activeTab === 'plan' ? 'active' : ''}`}
            onClick={() => setActiveTab('plan')}
          >
            3. Scene Planner & Coverage
          </button>
          <button
            type="button"
            className={`nav-item ${activeTab === 'render' ? 'active' : ''}`}
            onClick={() => setActiveTab('render')}
          >
            4. Review & Render
          </button>
        </nav>

        {/* Content Area */}
        <main className="pipeline-content">
          {error && (
            <div className="error-banner">
              <strong>Connection Warning:</strong> {error}
              <p className="error-hint">
                Ensure backend API server is running on port 8000:
                <code>uvicorn app.main:app --port 8000</code>
              </p>
            </div>
          )}

          <div className="panel-card">
            <h2>Feature Scaffold Initialized</h2>
            <p className="panel-desc">
              AI Animation Studio is mounted independently on <strong>Port 5174</strong> and calls the shared backend under
              <code>/api/v1/animation</code>.
            </p>

            {config && (
              <div className="specs-grid">
                <div className="spec-item">
                  <span className="spec-label">Canvas Format</span>
                  <span className="spec-value">{config.render_width} × {config.render_height} ({config.render_fps} fps)</span>
                </div>
                <div className="spec-item">
                  <span className="spec-label">LLM Provider</span>
                  <span className="spec-value">{health?.llm_provider} ({health?.llm_model})</span>
                </div>
                <div className="spec-item">
                  <span className="spec-label">TTS Engine</span>
                  <span className="spec-value">{health?.tts_provider}</span>
                </div>
                <div className="spec-item">
                  <span className="spec-label">Output Directory</span>
                  <span className="spec-value"><code>{config.output_dir}</code></span>
                </div>
              </div>
            )}

            <div className="scaffold-notice">
              <span className="notice-icon">ℹ️</span>
              <div>
                <strong>Independent Architecture Verification:</strong>
                <p>
                  This UI runs as an independent React application without importing Clipper components or Clipper business logic.
                  Milestone M1 (Render Prototype) and M2 (Scene Planner) implementations will mount here.
                </p>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

export default App;
