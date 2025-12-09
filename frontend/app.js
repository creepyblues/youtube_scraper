let currentResults = null;
let selectedMethod = 'compare';

document.addEventListener('DOMContentLoaded', () => {
    setupMethodButtons();
    setupTabs();
    setupKeyboardShortcuts();
});

function setupMethodButtons() {
    document.querySelectorAll('.method-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.method-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedMethod = btn.dataset.method;
        });
    });
}

function setupTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;

            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(`tab-${tabId}`).classList.add('active');
        });
    });
}

function setupKeyboardShortcuts() {
    document.getElementById('videoUrl').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            scrapeVideo();
        }
    });
}

async function scrapeVideo() {
    const url = document.getElementById('videoUrl').value.trim();

    if (!url) {
        showError('Please enter a YouTube URL');
        return;
    }

    if (!isValidYouTubeUrl(url)) {
        showError('Please enter a valid YouTube URL');
        return;
    }

    const includeComments = document.getElementById('includeComments').checked;
    const includeTranscript = document.getElementById('includeTranscript').checked;

    const btn = document.getElementById('scrapeBtn');
    const btnText = btn.querySelector('.btn-text');
    const btnLoader = btn.querySelector('.btn-loader');

    btn.disabled = true;
    btnText.classList.add('hidden');
    btnLoader.classList.remove('hidden');
    hideError();
    hideResults();

    try {
        const endpoint = getEndpoint();
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                url: url,
                include_comments: includeComments,
                include_transcript: includeTranscript
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to scrape video');
        }

        const data = await response.json();
        currentResults = data;

        displayResults(data);
    } catch (error) {
        showError(error.message);
    } finally {
        btn.disabled = false;
        btnText.classList.remove('hidden');
        btnLoader.classList.add('hidden');
    }
}

function getEndpoint() {
    const endpoints = {
        'compare': '/api/scrape/compare',
        'ytdlp': '/api/scrape/ytdlp',
        'youtube-api': '/api/scrape/youtube-api',
        'transcript': '/api/scrape/transcript',
        'transcript-ai': '/api/scrape/transcript-ai'
    };
    return endpoints[selectedMethod] || endpoints['compare'];
}

function isValidYouTubeUrl(url) {
    const patterns = [
        /youtube\.com\/watch\?v=/,
        /youtu\.be\//,
        /youtube\.com\/embed\//,
        /youtube\.com\/shorts\//
    ];
    return patterns.some(pattern => pattern.test(url));
}

function showError(message) {
    const section = document.getElementById('errorSection');
    const messageEl = document.getElementById('errorMessage');
    messageEl.textContent = message;
    section.classList.remove('hidden');
}

function hideError() {
    document.getElementById('errorSection').classList.add('hidden');
}

function hideResults() {
    document.getElementById('resultsSection').classList.add('hidden');
}

function displayResults(data) {
    const section = document.getElementById('resultsSection');
    section.classList.remove('hidden');

    if (selectedMethod === 'compare') {
        displayComparisonResults(data);
    } else {
        displaySingleResult(data);
    }
}

function displayComparisonResults(data) {
    const summarySection = document.getElementById('comparisonSummary');
    const summaryContent = document.getElementById('summaryContent');

    summarySection.classList.remove('hidden');
    summaryContent.innerHTML = generateComparisonSummaryHTML(data);

    const mergedData = mergeResults(data.results);

    renderOverviewTab(mergedData, data.results);
    renderEngagementTab(mergedData, data.results);
    renderTranscriptTab(mergedData, data.results);
    renderChaptersTab(mergedData, data.results);
    renderTagsTab(mergedData, data.results);
    renderThumbnailsTab(mergedData, data.results);
    renderTechnicalTab(mergedData, data.results);
    renderCommentsTab(mergedData, data.results);
    renderRawTab(data);
}

function displaySingleResult(data) {
    const summarySection = document.getElementById('comparisonSummary');
    summarySection.classList.add('hidden');

    if (!data.success) {
        showError(data.error || 'Failed to scrape video');
        return;
    }

    const results = [data];
    const mergedData = data.data;

    renderOverviewTab(mergedData, results);
    renderEngagementTab(mergedData, results);
    renderTranscriptTab(mergedData, results);
    renderChaptersTab(mergedData, results);
    renderTagsTab(mergedData, results);
    renderThumbnailsTab(mergedData, results);
    renderTechnicalTab(mergedData, results);
    renderCommentsTab(mergedData, results);
    renderRawTab(data);
}

function generateComparisonSummaryHTML(data) {
    const summary = data.comparison_summary || {};
    const succeeded = summary.methods_succeeded || [];
    const failed = summary.methods_failed || [];

    let html = `
        <div class="summary-card">
            <h3>Methods Status</h3>
            <div class="value">
                ${succeeded.map(m => `<span class="method-badge success">${m}</span>`).join('')}
                ${failed.map(f => `<span class="method-badge error">${f.method}</span>`).join('')}
            </div>
        </div>
        <div class="summary-card">
            <h3>Execution Time</h3>
            <div class="value">
                ${data.results.filter(r => r.success).map(r =>
                    `<div>${r.method}: ${r.execution_time_ms}ms</div>`
                ).join('')}
            </div>
        </div>
        <div class="summary-card">
            <h3>Fields Extracted</h3>
            <div class="value">
                ${data.results.filter(r => r.success).map(r =>
                    `<div>${r.method}: ${r.fields_extracted} fields</div>`
                ).join('')}
            </div>
        </div>
    `;

    if (summary.best_for && Object.keys(summary.best_for).length > 0) {
        html += `
            <div class="summary-card">
                <h3>Best For</h3>
                <div class="value">
                    ${Object.entries(summary.best_for).map(([field, info]) =>
                        `<div>${field}: <span class="method-badge">${info.method}</span></div>`
                    ).join('')}
                </div>
            </div>
        `;
    }

    return html;
}

function mergeResults(results) {
    const merged = {
        video_id: '',
        title: '',
        description: '',
        upload_date: '',
        channel: null,
        engagement: null,
        technical: null,
        classification: null,
        thumbnails: [],
        chapters: [],
        transcript: [],
        comments: []
    };

    for (const result of results) {
        if (!result.success || !result.data) continue;
        const data = result.data;

        if (!merged.video_id && data.video_id) merged.video_id = data.video_id;
        if (!merged.title && data.title) merged.title = data.title;
        if (!merged.description && data.description) merged.description = data.description;
        if (!merged.upload_date && data.upload_date) merged.upload_date = data.upload_date;

        if (!merged.channel && data.channel) merged.channel = data.channel;
        if (!merged.engagement && data.engagement) merged.engagement = data.engagement;
        if (!merged.technical && data.technical) merged.technical = data.technical;
        if (!merged.classification && data.classification) merged.classification = data.classification;

        if (data.thumbnails && data.thumbnails.length > merged.thumbnails.length) {
            merged.thumbnails = data.thumbnails;
        }
        if (data.chapters && data.chapters.length > merged.chapters.length) {
            merged.chapters = data.chapters;
        }
        if (data.transcript && data.transcript.length > merged.transcript.length) {
            merged.transcript = data.transcript;
        }
        if (data.comments && data.comments.length > merged.comments.length) {
            merged.comments = data.comments;
        }
    }

    return merged;
}

function renderOverviewTab(data, results) {
    const container = document.getElementById('tab-overview');

    let html = `
        <div class="data-grid">
            <div class="data-card">
                <div class="label">Video ID</div>
                <div class="value">${data.video_id || 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">Title</div>
                <div class="value">${escapeHtml(data.title) || 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">Upload Date</div>
                <div class="value">${formatDate(data.upload_date) || 'N/A'}</div>
            </div>
    `;

    if (data.channel) {
        html += `
            <div class="data-card">
                <div class="label">Channel</div>
                <div class="value">
                    <a href="${data.channel.url || '#'}" target="_blank" style="color: var(--primary);">
                        ${escapeHtml(data.channel.name)}
                    </a>
                </div>
            </div>
            <div class="data-card">
                <div class="label">Subscribers</div>
                <div class="value">${formatNumber(data.channel.subscriber_count) || 'N/A'}</div>
            </div>
        `;
    }

    html += `</div>`;

    if (data.description) {
        html += `
            <h3 style="margin: 1.5rem 0 1rem;">Description</h3>
            <div class="description-box">${escapeHtml(data.description)}</div>
        `;
    }

    container.innerHTML = html;
}

function renderEngagementTab(data, results) {
    const container = document.getElementById('tab-engagement');
    const engagement = data.engagement || {};

    container.innerHTML = `
        <div class="data-grid">
            <div class="data-card">
                <div class="label">Views</div>
                <div class="value large">${formatNumber(engagement.view_count) || 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">Likes</div>
                <div class="value large">${formatNumber(engagement.like_count) || 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">Comments</div>
                <div class="value large">${formatNumber(engagement.comment_count) || 'N/A'}</div>
            </div>
        </div>
    `;
}

let transcriptViewMode = 'timestamped';

function renderTranscriptTab(data, results) {
    const container = document.getElementById('tab-transcript');
    const transcript = data.transcript || [];

    if (transcript.length === 0) {
        container.innerHTML = '<div class="no-data">No transcript available</div>';
        return;
    }

    // Store transcript data for toggling
    container.dataset.transcript = JSON.stringify(transcript);

    const wordCount = transcript.reduce((acc, seg) => acc + seg.text.split(/\s+/).length, 0);

    // Check if this was AI transcribed
    const rawData = data.raw_data || {};
    const isAITranscribed = rawData.is_ai_transcribed === true;
    const whisperModel = rawData.whisper_model || '';

    let html = `
        <div class="transcript-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 1rem;">
            <div style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
                <p style="color: var(--text-secondary); margin: 0;">
                    ${transcript.length} segments · ~${wordCount.toLocaleString()} words
                </p>
                ${isAITranscribed ? `
                    <span class="ai-badge" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 500;">
                        🤖 AI Transcribed${whisperModel ? ` (${whisperModel})` : ''}
                    </span>
                ` : ''}
            </div>
            <div class="transcript-toggle" style="display: flex; gap: 0.5rem;">
                <button class="toggle-btn ${transcriptViewMode === 'timestamped' ? 'active' : ''}" data-mode="timestamped" onclick="toggleTranscriptView('timestamped')">
                    Timestamped
                </button>
                <button class="toggle-btn ${transcriptViewMode === 'clean' ? 'active' : ''}" data-mode="clean" onclick="toggleTranscriptView('clean')">
                    Clean Text
                </button>
                <button class="copy-btn" onclick="copyTranscript()" title="Copy to clipboard">
                    📋 Copy
                </button>
            </div>
        </div>
        <div id="transcript-content"></div>
    `;

    container.innerHTML = html;
    updateTranscriptContent(transcript);
}

function toggleTranscriptView(mode) {
    transcriptViewMode = mode;

    // Update button states
    document.querySelectorAll('.transcript-toggle .toggle-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Re-render content
    const container = document.getElementById('tab-transcript');
    const transcript = JSON.parse(container.dataset.transcript || '[]');
    updateTranscriptContent(transcript);
}

function updateTranscriptContent(transcript) {
    const contentContainer = document.getElementById('transcript-content');

    if (transcriptViewMode === 'timestamped') {
        let html = '<div class="transcript-box">';
        for (const segment of transcript) {
            const timestamp = formatTimestamp(segment.start);
            html += `
                <div class="transcript-segment">
                    <span class="timestamp">${timestamp}</span>
                    <span class="text">${escapeHtml(segment.text)}</span>
                </div>
            `;
        }
        html += '</div>';
        contentContainer.innerHTML = html;
    } else {
        const cleanText = transcript.map(seg => seg.text).join(' ');
        contentContainer.innerHTML = `
            <div class="transcript-box clean-text" style="white-space: pre-wrap; line-height: 1.8;">
                ${escapeHtml(cleanText)}
            </div>
        `;
    }
}

function copyTranscript() {
    const container = document.getElementById('tab-transcript');
    const transcript = JSON.parse(container.dataset.transcript || '[]');

    let textToCopy;
    if (transcriptViewMode === 'timestamped') {
        textToCopy = transcript.map(seg => `[${formatTimestamp(seg.start)}] ${seg.text}`).join('\n');
    } else {
        textToCopy = transcript.map(seg => seg.text).join(' ');
    }

    navigator.clipboard.writeText(textToCopy).then(() => {
        const copyBtn = document.querySelector('.copy-btn');
        const originalText = copyBtn.textContent;
        copyBtn.textContent = '✓ Copied!';
        setTimeout(() => {
            copyBtn.textContent = originalText;
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

function renderChaptersTab(data, results) {
    const container = document.getElementById('tab-chapters');
    const chapters = data.chapters || [];

    if (chapters.length === 0) {
        container.innerHTML = '<div class="no-data">No chapters available</div>';
        return;
    }

    let html = '<div class="chapters-list">';

    for (const chapter of chapters) {
        const timestamp = formatTimestamp(chapter.start_time);
        html += `
            <div class="chapter-item">
                <span class="time">${timestamp}</span>
                <span class="title">${escapeHtml(chapter.title)}</span>
            </div>
        `;
    }

    html += '</div>';
    container.innerHTML = html;
}

function renderTagsTab(data, results) {
    const container = document.getElementById('tab-tags');
    const classification = data.classification || {};
    const tags = classification.tags || [];
    const hashtags = classification.hashtags || [];

    if (tags.length === 0 && hashtags.length === 0) {
        container.innerHTML = '<div class="no-data">No tags available</div>';
        return;
    }

    let html = '';

    if (classification.category) {
        html += `
            <div class="data-card" style="margin-bottom: 1rem;">
                <div class="label">Category</div>
                <div class="value">${escapeHtml(classification.category)}</div>
            </div>
        `;
    }

    if (hashtags.length > 0) {
        html += `
            <h3 style="margin-bottom: 0.75rem;">Hashtags</h3>
            <div class="tags-container" style="margin-bottom: 1.5rem;">
                ${hashtags.map(h => `<span class="tag hashtag">#${escapeHtml(h)}</span>`).join('')}
            </div>
        `;
    }

    if (tags.length > 0) {
        html += `
            <h3 style="margin-bottom: 0.75rem;">Tags</h3>
            <div class="tags-container">
                ${tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
            </div>
        `;
    }

    container.innerHTML = html;
}

function renderThumbnailsTab(data, results) {
    const container = document.getElementById('tab-thumbnails');
    const thumbnails = data.thumbnails || [];

    if (thumbnails.length === 0) {
        container.innerHTML = '<div class="no-data">No thumbnails available</div>';
        return;
    }

    const sortedThumbnails = [...thumbnails].sort((a, b) =>
        (b.width || 0) * (b.height || 0) - (a.width || 0) * (a.height || 0)
    );

    let html = '<div class="thumbnails-grid">';

    for (const thumb of sortedThumbnails) {
        html += `
            <div class="thumbnail-card">
                <img src="${thumb.url}" alt="Thumbnail" loading="lazy">
                <div class="info">
                    ${thumb.width && thumb.height ? `${thumb.width} × ${thumb.height}` : 'Unknown size'}
                </div>
            </div>
        `;
    }

    html += '</div>';
    container.innerHTML = html;
}

function renderTechnicalTab(data, results) {
    const container = document.getElementById('tab-technical');
    const technical = data.technical || {};

    container.innerHTML = `
        <div class="data-grid">
            <div class="data-card">
                <div class="label">Duration</div>
                <div class="value">${technical.duration_string || formatDuration(technical.duration) || 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">Definition</div>
                <div class="value">${(technical.definition || '').toUpperCase() || 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">Dimension</div>
                <div class="value">${(technical.dimension || '').toUpperCase() || 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">Frame Rate</div>
                <div class="value">${technical.fps ? `${technical.fps} fps` : 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">Video Codec</div>
                <div class="value">${technical.video_codec || 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">Audio Codec</div>
                <div class="value">${technical.audio_codec || 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">Bitrate</div>
                <div class="value">${technical.bitrate ? `${Math.round(technical.bitrate)} kbps` : 'N/A'}</div>
            </div>
            <div class="data-card">
                <div class="label">File Size</div>
                <div class="value">${formatFileSize(technical.filesize) || 'N/A'}</div>
            </div>
        </div>
    `;
}

function renderCommentsTab(data, results) {
    const container = document.getElementById('tab-comments');
    const comments = data.comments || [];

    if (comments.length === 0) {
        container.innerHTML = '<div class="no-data">No comments available (enable "Include Comments" and rescrape)</div>';
        return;
    }

    let html = `
        <p style="margin-bottom: 1rem; color: var(--text-secondary);">
            Showing ${comments.length} comments
        </p>
        <div class="comments-list">
    `;

    for (const comment of comments) {
        html += `
            <div class="comment-item">
                <div class="author">${escapeHtml(comment.author)}</div>
                <div class="text">${escapeHtml(comment.text)}</div>
                <div class="meta">
                    <span>👍 ${formatNumber(comment.likes)}</span>
                    ${comment.reply_count ? `<span>💬 ${comment.reply_count} replies</span>` : ''}
                </div>
            </div>
        `;
    }

    html += '</div>';
    container.innerHTML = html;
}

function renderRawTab(data) {
    const container = document.getElementById('tab-raw');

    const displayData = { ...data };
    if (displayData.results) {
        displayData.results = displayData.results.map(r => ({
            ...r,
            data: r.data ? { ...r.data, raw_data: '[truncated]' } : null
        }));
    } else if (displayData.data) {
        displayData.data = { ...displayData.data, raw_data: '[truncated]' };
    }

    container.innerHTML = `
        <div class="raw-json">
            <pre>${escapeHtml(JSON.stringify(displayData, null, 2))}</pre>
        </div>
    `;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatNumber(num) {
    if (num === null || num === undefined) return null;
    return new Intl.NumberFormat().format(num);
}

function formatDate(dateStr) {
    if (!dateStr) return null;

    if (/^\d{8}$/.test(dateStr)) {
        const year = dateStr.slice(0, 4);
        const month = dateStr.slice(4, 6);
        const day = dateStr.slice(6, 8);
        return `${year}-${month}-${day}`;
    }

    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString();
    } catch {
        return dateStr;
    }
}

function formatTimestamp(seconds) {
    if (seconds === null || seconds === undefined) return '00:00';

    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

function formatDuration(seconds) {
    if (!seconds) return null;

    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hours > 0) {
        return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatFileSize(bytes) {
    if (!bytes) return null;

    const units = ['B', 'KB', 'MB', 'GB'];
    let unitIndex = 0;
    let size = bytes;

    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }

    return `${size.toFixed(2)} ${units[unitIndex]}`;
}
