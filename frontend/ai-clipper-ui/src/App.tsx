import { useEffect, useState } from 'react';
import { apiClient } from './lib/api/client';
import type { HealthResponse } from './lib/api/types';
import { ReviewView } from './features/candidates';
import { config } from './config/env';
import './App.css';

export function App() {
  const [activeTab, setActiveTab] = useState<'review' | 'diagnostics'>('review');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<string | null>(null);

  const fetchHealth = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getHealth();
      setHealth(data);
      setLastChecked(new Date().toLocaleTimeString());
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to connect to backend';
      setError(msg);
      setHealth(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let ignore = false;

    async function initCheck() {
      try {
        const data = await apiClient.getHealth();
        if (!ignore) {
          setHealth(data);
          setLastChecked(new Date().toLocaleTimeString());
        }
      } catch (err: unknown) {
        if (!ignore) {
          const msg = err instanceof Error ? err.message : 'Failed to connect to backend';
          setError(msg);
          setHealth(null);
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    initCheck();
    return () => {
      ignore = true;
    };
  }, []);

  return (
    <div className="layout">
      <header className="header">
        <div className="header-brand">
          <div className="logo-badge">AI</div>
          <div>
            <h1 className="header-title">AI Video Clipper</h1>
            <p className="header-subtitle">Intelligent Short-Form Repurposing Engine</p>
          </div>
        </div>
        <div className="header-status">
          <span className={`status-pill ${health ? 'status-ok' : 'status-err'}`}>
            <span className="dot" />
            {loading ? 'Checking...' : health ? 'Backend Connected' : 'Backend Disconnected'}
          </span>
          <button className="btn-secondary" onClick={fetchHealth} disabled={loading}>
            {loading ? 'Pinging...' : 'Refresh'}
          </button>
        </div>
      </header>

      <main className="content">
        {/* Navigation Tabs */}
        <div className="nav-tabs">
          <button
            className={`tab-btn ${activeTab === 'review' ? 'active' : ''}`}
            onClick={() => setActiveTab('review')}
          >
            🎬 Candidate Review & Playback
          </button>
          <button
            className={`tab-btn ${activeTab === 'diagnostics' ? 'active' : ''}`}
            onClick={() => setActiveTab('diagnostics')}
          >
            ⚙ System Diagnostics
          </button>
        </div>

        {activeTab === 'review' ? (
          <ReviewView />
        ) : (
          <>
            {/* Hero Section */}
            <section className="card hero-card">
              <div className="hero-text">
                <h2>Transform Long-Form Speech into Viral Vertical Clips</h2>
                <p>
                  AI Video Clipper analyzes speech-heavy video transcripts, identifies the most compelling
                  candidate moments conditioned on your editorial intent, frames landscape footage into vertical
                  9:16 videos, and burns synchronized captions.
                </p>
              </div>
              <div className="hero-meta">
                <div className="meta-item">
                  <span className="meta-label">Version</span>
                  <span className="meta-value">v{config.appVersion}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">Target Duration</span>
                  <span className="meta-value">15s – 45s (max 60s)</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">API Endpoint</span>
                  <span className="meta-value">{config.apiBaseUrl}</span>
                </div>
              </div>
            </section>

            {/* Pipeline Stages */}
            <section className="section">
              <h3 className="section-title">Core Processing Pipeline</h3>
              <div className="pipeline-grid">
                <div className="stage-card">
                  <div className="stage-num">01</div>
                  <h4>Direct Upload & Probe</h4>
                  <p>Direct-to-R2 signed uploads with ffprobe audio & stream validation.</p>
                </div>
                <div className="stage-card">
                  <div className="stage-num">02</div>
                  <h4>Full Transcription</h4>
                  <p>Audio extraction and whole-source Whisper transcription with word timings.</p>
                </div>
                <div className="stage-card">
                  <div className="stage-num">03</div>
                  <h4>Editorial Analysis</h4>
                  <p>Goal-conditioned candidate discovery, structured dimension scoring, and global ranking.</p>
                </div>
                <div className="stage-card">
                  <div className="stage-num">04</div>
                  <h4>Candidate Review</h4>
                  <p>Human review of hooks, rationale, and transcript evidence with timestamp trimming.</p>
                </div>
                <div className="stage-card">
                  <div className="stage-num">05</div>
                  <h4>Framing & Render</h4>
                  <p>9:16 vertical crop/fit framing with ASS-styled synchronized captions.</p>
                </div>
              </div>
            </section>

            {/* System Diagnostics & Health Status */}
            <section className="section">
              <div className="section-header">
                <h3 className="section-title">System & Subsystem Status</h3>
                {lastChecked && <span className="timestamp">Last verified: {lastChecked}</span>}
              </div>

              {error && (
                <div className="banner banner-error">
                  <strong>Connection Notice:</strong> {error}. Ensure the FastAPI backend is running at{' '}
                  <code>{config.apiBaseUrl}</code>.
                </div>
              )}

              <div className="grid-subsystems">
                <div className="status-item">
                  <div className="status-item-header">
                    <span className="subsystem-name">Media Engine (FFmpeg & FFprobe)</span>
                    <span className={`badge ${health?.ffmpeg_available ? 'badge-success' : 'badge-warning'}`}>
                      {health?.ffmpeg_available ? 'Ready' : 'Not Detected'}
                    </span>
                  </div>
                  <p className="subsystem-desc">
                    {health?.subsystems?.media_engine?.details || 'Probing system PATH for FFmpeg / FFprobe binaries...'}
                  </p>
                </div>

                <div className="status-item">
                  <div className="status-item-header">
                    <span className="subsystem-name">Neon Postgres Database</span>
                    <span className={`badge ${health?.subsystems?.database?.configured ? 'badge-success' : 'badge-neutral'}`}>
                      {health?.subsystems?.database?.status || 'Unconfigured'}
                    </span>
                  </div>
                  <p className="subsystem-desc">
                    {health?.subsystems?.database?.details || 'DATABASE_URL configuration in backend/.env'}
                  </p>
                </div>

                <div className="status-item">
                  <div className="status-item-header">
                    <span className="subsystem-name">Cloudflare R2 Object Storage</span>
                    <span className={`badge ${health?.subsystems?.object_storage?.configured ? 'badge-success' : 'badge-neutral'}`}>
                      {health?.subsystems?.object_storage?.status || 'Unconfigured'}
                    </span>
                  </div>
                  <p className="subsystem-desc">
                    {health?.subsystems?.object_storage?.details || 'Private R2 bucket credentials in backend/.env'}
                  </p>
                </div>

                <div className="status-item">
                  <div className="status-item-header">
                    <span className="subsystem-name">Whisper Transcription Adapter</span>
                    <span className={`badge ${health?.subsystems?.transcription?.configured ? 'badge-success' : 'badge-neutral'}`}>
                      {health?.subsystems?.transcription?.status || 'Configured'}
                    </span>
                  </div>
                  <p className="subsystem-desc">
                    {health?.subsystems?.transcription?.details || 'Local Whisper model selection in backend/.env'}
                  </p>
                </div>

                <div className="status-item">
                  <div className="status-item-header">
                    <span className="subsystem-name">LLM Evaluation Adapter</span>
                    <span className={`badge ${health?.subsystems?.llm?.configured ? 'badge-success' : 'badge-neutral'}`}>
                      {health?.subsystems?.llm?.status || 'Unconfigured'}
                    </span>
                  </div>
                  <p className="subsystem-desc">
                    {health?.subsystems?.llm?.details || 'LLM provider and API key in backend/.env'}
                  </p>
                </div>
              </div>
            </section>

            {/* Development Instructions */}
            <section className="card notice-card">
              <h4>Phase 3 Review Workflow Ready</h4>
              <p>
                The local review workflow connects to candidate and rendering artifacts generated in <code>outputs/</code>.
              </p>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
