import React, { useEffect, useState } from 'react';
import { apiClient } from '../../lib/api/client';
import type {
  CaptionStyleOption,
  ReviewCandidateItem,
  ReviewDetailResponse,
  ReviewRunSummary,
} from '../../lib/api/types';
import './ReviewView.css';

export function ReviewView() {
  const [runs, setRuns] = useState<ReviewRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>('');
  const [runDetails, setRunDetails] = useState<ReviewDetailResponse | null>(null);
  const [activeCandidateId, setActiveCandidateId] = useState<string | null>(null);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<string>>(new Set());
  const [expandedEvidenceIds, setExpandedEvidenceIds] = useState<Set<string>>(new Set());

  // Caption Styling v1 state
  const [captionStyles, setCaptionStyles] = useState<CaptionStyleOption[]>([]);
  const [selectedStyleId, setSelectedStyleId] = useState<string>('modern-box');

  const [loadingRuns, setLoadingRuns] = useState<boolean>(true);
  const [loadingDetails, setLoadingDetails] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Load runs on mount
  useEffect(() => {
    let ignore = false;
    async function fetchRunsAndStyles() {
      setLoadingRuns(true);
      setError(null);
      try {
        const [availableRuns, availableStyles] = await Promise.all([
          apiClient.listReviewRuns(),
          apiClient.listCaptionStyles().catch(() => [] as CaptionStyleOption[]),
        ]);
        if (!ignore) {
          setRuns(availableRuns);
          setCaptionStyles(availableStyles);
          if (availableRuns.length > 0) {
            setSelectedRunId(availableRuns[0].run_id);
          }
        }
      } catch (err: unknown) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : 'Failed to fetch candidate runs');
        }
      } finally {
        if (!ignore) {
          setLoadingRuns(false);
        }
      }
    }

    fetchRunsAndStyles();
    return () => {
      ignore = true;
    };
  }, []);

  // Load run details when selectedRunId changes
  useEffect(() => {
    if (!selectedRunId) {
      return;
    }

    let ignore = false;
    async function fetchDetails() {
      setLoadingDetails(true);
      setError(null);
      try {
        const details = await apiClient.getReviewRunDetails(selectedRunId);
        if (!ignore) {
          setRunDetails(details);
          // Default active preview candidate to first candidate or first rendered candidate
          if (details.candidates.length > 0) {
            const firstRendered = details.candidates.find((c) => c.render_info.is_rendered);
            setActiveCandidateId(firstRendered ? firstRendered.id : details.candidates[0].id);
          } else {
            setActiveCandidateId(null);
          }
          // Reset selection state for new run
          setSelectedCandidateIds(new Set());
        }
      } catch (err: unknown) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : 'Failed to fetch run details');
          setRunDetails(null);
        }
      } finally {
        if (!ignore) {
          setLoadingDetails(false);
        }
      }
    }

    fetchDetails();
    return () => {
      ignore = true;
    };
  }, [selectedRunId]);

  const handleRefresh = async () => {
    setLoadingRuns(true);
    setError(null);
    try {
      const availableRuns = await apiClient.listReviewRuns();
      setRuns(availableRuns);
      if (availableRuns.length > 0) {
        if (!selectedRunId || !availableRuns.some((r) => r.run_id === selectedRunId)) {
          setSelectedRunId(availableRuns[0].run_id);
        } else {
          // Re-fetch current run details
          const details = await apiClient.getReviewRunDetails(selectedRunId);
          setRunDetails(details);
        }
      } else {
        setSelectedRunId('');
        setRunDetails(null);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to refresh runs');
    } finally {
      setLoadingRuns(false);
    }
  };

  const toggleSelectCandidate = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedCandidateIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (!runDetails) return;
    if (selectedCandidateIds.size === runDetails.candidates.length) {
      setSelectedCandidateIds(new Set());
    } else {
      setSelectedCandidateIds(new Set(runDetails.candidates.map((c) => c.id)));
    }
  };

  const toggleEvidence = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedEvidenceIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const activeCandidate: ReviewCandidateItem | undefined = runDetails?.candidates.find(
    (c) => c.id === activeCandidateId
  );

  const formatSeconds = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const formatBytes = (bytes?: number | null) => {
    if (!bytes) return '';
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(1)} MB`;
  };

  if (loadingRuns) {
    return (
      <div className="card empty-review-state">
        <p>Scanning outputs for candidate runs...</p>
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="empty-review-state">
        <h3>No Candidate Runs Found</h3>
        <p>No discovery or rendering runs were detected in the local <code>outputs/</code> folder.</p>
        <p style={{ marginTop: '0.75rem', color: 'var(--text-secondary)' }}>
          Run the transcription and candidate discovery pipelines locally to produce candidates:
        </p>
        <code className="code-snippet">
          # 1. Transcribe source video<br />
          python -m app.cli.process_local &lt;video.mp4&gt;<br /><br />
          # 2. Discover viral candidates<br />
          python -m app.cli.discover_candidates outputs/&lt;run&gt;/transcript.json<br /><br />
          # 3. Render vertical 9:16 clips<br />
          python -m app.cli.render_clips &lt;video.mp4&gt; --candidates outputs/&lt;run&gt;/candidates.json --transcript outputs/&lt;run&gt;/transcript.json
        </code>
        <button className="btn-secondary" onClick={handleRefresh} style={{ marginTop: '1rem' }}>
          Scan Again
        </button>
      </div>
    );
  }

  return (
    <div className="review-container">
      {/* Top Toolbar: Run selector */}
      <div className="review-toolbar">
        <div className="run-selector-group">
          <label htmlFor="run-select" style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Processing Run:
          </label>
          <select
            id="run-select"
            className="run-select"
            value={selectedRunId}
            onChange={(e) => setSelectedRunId(e.target.value)}
          >
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.source_filename} ({r.total_candidates} candidates, {r.rendered_candidates} rendered) — {r.created_at.slice(0, 10)}
              </option>
            ))}
          </select>
        </div>

        <button className="btn-secondary" onClick={handleRefresh} disabled={loadingDetails}>
          {loadingDetails ? 'Loading...' : 'Refresh Runs'}
        </button>
      </div>

      {error && (
        <div className="banner banner-error">
          <strong>Review Error:</strong> {error}
        </div>
      )}

      {runDetails && (
        <>
          {/* Run Metadata Summary Bar */}
          <div className="run-meta-bar">
            <div className="run-meta-item">
              <span className="run-meta-label">Source File</span>
              <span className="run-meta-val">{runDetails.summary.source_filename}</span>
            </div>
            <div className="run-meta-item">
              <span className="run-meta-label">Source Duration</span>
              <span className="run-meta-val">{formatSeconds(runDetails.summary.source_duration_seconds)} ({runDetails.summary.source_duration_seconds.toFixed(1)}s)</span>
            </div>
            <div className="run-meta-item">
              <span className="run-meta-label">Editorial Goal</span>
              <span className="run-meta-val" style={{ textTransform: 'capitalize' }}>
                {runDetails.summary.editorial_goal}
              </span>
            </div>
            <div className="run-meta-item">
              <span className="run-meta-label">Candidates</span>
              <span className="run-meta-val">{runDetails.summary.total_candidates}</span>
            </div>
            <div className="run-meta-item">
              <span className="run-meta-label">Rendered Clips</span>
              <span className="run-meta-val" style={{ color: runDetails.summary.rendered_candidates > 0 ? '#34d399' : 'var(--text-muted)' }}>
                {runDetails.summary.rendered_candidates} of {runDetails.summary.total_candidates}
              </span>
            </div>
          </div>

          {/* Main Content Layout: Candidates List + Sticky 9:16 Video Player */}
          <div className="review-main-layout">
            {/* Candidate List Column */}
            <div className="candidate-list-col">
              <div className="list-header">
                <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                  Showing <strong>{runDetails.candidates.length}</strong> ranked moments
                </span>
                <div className="list-actions">
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginRight: '0.5rem' }}>
                    {selectedCandidateIds.size} selected
                  </span>
                  <button className="btn-secondary" style={{ padding: '0.3rem 0.6rem', fontSize: '0.8rem' }} onClick={toggleSelectAll}>
                    {selectedCandidateIds.size === runDetails.candidates.length ? 'Deselect All' : 'Select All'}
                  </button>
                </div>
              </div>

              {runDetails.candidates.map((cand, idx) => {
                const isActive = cand.id === activeCandidateId;
                const isSelected = selectedCandidateIds.has(cand.id);
                const isEvidenceExpanded = expandedEvidenceIds.has(cand.id);

                return (
                  <div
                    key={cand.id}
                    className={`candidate-card ${isActive ? 'active-preview' : ''}`}
                    onClick={() => setActiveCandidateId(cand.id)}
                  >
                    <div className="candidate-card-header">
                      <div className="candidate-header-left">
                        <input
                          type="checkbox"
                          className="candidate-checkbox"
                          checked={isSelected}
                          onChange={(e) => toggleSelectCandidate(cand.id, e as unknown as React.MouseEvent)}
                          onClick={(e) => e.stopPropagation()}
                          title="Select candidate for action"
                        />
                        <span className="candidate-rank">#{idx + 1}</span>
                        <span className={`score-badge ${cand.overall_score >= 80 ? 'score-high' : 'score-med'}`}>
                          ★ {cand.overall_score}
                        </span>
                      </div>

                      <div className="candidate-badges">
                        <span
                          className={`render-badge ${cand.render_info.is_rendered ? 'rendered' : 'unrendered'}`}
                        >
                          {cand.render_info.is_rendered ? '✓ 9:16 Rendered' : 'Not Rendered'}
                        </span>
                      </div>
                    </div>

                    <h4 className="candidate-hook">{cand.hook}</h4>

                    <div className="candidate-meta-row">
                      <span className="meta-pill">
                        ⏱ {cand.duration_seconds.toFixed(1)}s ({cand.start_seconds.toFixed(1)}s – {cand.end_seconds.toFixed(1)}s)
                      </span>
                      <span className="meta-pill">
                        🎯 {cand.editorial_goal}
                      </span>
                    </div>

                    <p className="candidate-rationale">{cand.rationale}</p>

                    {/* Collapsible Evidence & Transcript */}
                    <div className="candidate-accordion">
                      <button
                        className="accordion-toggle"
                        onClick={(e) => toggleEvidence(cand.id, e)}
                      >
                        {isEvidenceExpanded ? '▼ Hide Spoken Evidence' : '► View Spoken Evidence & Transcript'}
                      </button>

                      {isEvidenceExpanded && (
                        <div style={{ marginTop: '0.5rem' }}>
                          {cand.evidence_quotes && cand.evidence_quotes.length > 0 && (
                            <div className="evidence-box">
                              {cand.evidence_quotes.map((quote, qIdx) => (
                                <div key={qIdx} className="evidence-quote">
                                  "{quote}"
                                </div>
                              ))}
                            </div>
                          )}
                          <div className="transcript-excerpt-box">
                            <strong>Excerpt:</strong> "{cand.transcript_excerpt}"
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Dedicated Player Column */}
            <div className="player-col">
              <div className="player-card">
                <div className="player-title-row">
                  <h4 className="player-title">9:16 Vertical Preview</h4>
                  {activeCandidate && (
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      Clip: {activeCandidate.id}
                    </span>
                  )}
                </div>

                {/* 9:16 Video Frame */}
                <div className="video-frame-916">
                  {activeCandidate && activeCandidate.render_info.is_rendered && activeCandidate.render_info.video_url ? (
                    <video
                      key={activeCandidate.render_info.video_url}
                      className="rendered-video-player"
                      controls
                      autoPlay={false}
                      playsInline
                      preload="metadata"
                      src={apiClient.resolveMediaUrl(activeCandidate.render_info.video_url)}
                    >
                      Your browser does not support HTML5 MP4 playback.
                    </video>
                  ) : (
                    <div className="player-placeholder">
                      <div className="placeholder-icon">🎬</div>
                      <strong>Clip Not Rendered</strong>
                      <p className="placeholder-text">
                        {activeCandidate
                          ? `Candidate ${activeCandidate.id} has not been rendered into a vertical MP4 yet.`
                          : 'Select a candidate to preview.'}
                      </p>
                      {activeCandidate && (
                        <code style={{ fontSize: '0.72rem', wordBreak: 'break-all', textAlign: 'left', marginTop: '0.5rem' }}>
                          python -m app.cli.render_clips &lt;source_video&gt; --candidates outputs/{selectedRunId}/candidates.json --transcript outputs/{selectedRunId}/transcript.json --clip-id {activeCandidate.id} --caption-style {selectedStyleId}
                        </code>
                      )}
                    </div>
                  )}
                </div>

                {/* Caption Style Selector & Live Visual Badge */}
                {captionStyles.length > 0 && (
                  <div className="caption-style-section">
                    <div className="caption-style-header">
                      <label htmlFor="caption-style-select" className="caption-style-label">
                        Caption Preset:
                      </label>
                      <span className="caption-style-desc">
                        {captionStyles.find((s) => s.style_id === selectedStyleId)?.description}
                      </span>
                    </div>

                    <div className="caption-style-controls">
                      <select
                        id="caption-style-select"
                        className="caption-style-select"
                        value={selectedStyleId}
                        onChange={(e) => setSelectedStyleId(e.target.value)}
                      >
                        {captionStyles.map((style) => (
                          <option key={style.style_id} value={style.style_id}>
                            {style.display_name} {style.style_id === 'modern-box' ? '(Default)' : ''}
                          </option>
                        ))}
                      </select>

                      {/* Live Style Visual Badge Preview */}
                      {(() => {
                        const current = captionStyles.find((s) => s.style_id === selectedStyleId);
                        if (!current) return null;
                        return (
                          <div className="caption-preview-badge-container">
                            <span className="caption-preview-badge" style={current.preview_css as React.CSSProperties}>
                              {current.sample_text}
                            </span>
                          </div>
                        );
                      })()}
                    </div>
                  </div>
                )}

                {/* Player Metadata & Actions */}
                {activeCandidate && (
                  <div className="player-footer">
                    <div className="player-meta-info">
                      <span>Duration: {activeCandidate.duration_seconds.toFixed(1)}s</span>
                      {activeCandidate.render_info.file_size_bytes && (
                        <span>Size: {formatBytes(activeCandidate.render_info.file_size_bytes)}</span>
                      )}
                    </div>

                    {activeCandidate.render_info.is_rendered && activeCandidate.render_info.download_url ? (
                      <a
                        href={apiClient.resolveMediaUrl(activeCandidate.render_info.download_url)}
                        download={activeCandidate.render_info.clip_filename || `${activeCandidate.id}.mp4`}
                        className="btn-download-clip"
                      >
                        ↓ Download Rendered MP4
                      </a>
                    ) : (
                      <button className="btn-download-clip" disabled>
                        Render Required to Download
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
