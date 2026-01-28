/**
 * Iris v3 - Main Application JavaScript
 * WebSocket communication, utilities, and initialization
 *
 * Dependencies:
 *   - marked.js (markdown parsing)
 *   - highlight.js (syntax highlighting)
 *   - /static/js/tts-queue.js (TTSQueue class)
 *   - /static/js/pip-player.js (PiPVideoPlayer class)
 *   - /static/audio_in.js (VOX controls)
 *
 * Load order:
 *   1. External libs (marked, highlight, hls.js)
 *   2. audio_in.js
 *   3. tts-queue.js
 *   4. pip-player.js
 *   5. main.js (this file)
 */

// ============================================================
// Global Instances - Created after DOM load
// ============================================================
let ttsQueue = null;
let pipPlayer = null;

// ============================================================
// Global State Variables
// ============================================================
let ws = null;
let isStreaming = false;
let currentAssistantMessage = null;
let currentAssistantText = '';
let currentContextLevel = null;
let lastKvCacheMetrics = null;
let currentThinkingContent = '';
let attachedImages = [];
let attachedDocuments = [];  // {content: base64, filename: string, size: number}

// DOM Elements (initialized after DOM load)
let chatContainer, messageInput, sendButton, stopButton, statusDiv;
let messageCount, sessionInfo, tokenInfo, protocolInfo;
let imageUpload, imagePreviewContainer, uploadButton;
let documentUpload, documentPreviewContainer, documentUploadButton;
let speechToggle;

// ============================================================
// Marked.js Configuration
// ============================================================
marked.setOptions({
    highlight: function(code, language) {
        if (language && hljs.getLanguage(language)) {
            return hljs.highlight(code, { language: language }).value;
        }
        return hljs.highlightAuto(code).value;
    },
    breaks: true,
    gfm: true
});

// ============================================================
// DOM Initialization
// ============================================================
function initDOMElements() {
    chatContainer = document.getElementById('chatContainer');
    messageInput = document.getElementById('messageInput');
    sendButton = document.getElementById('sendButton');
    stopButton = document.getElementById('stopButton');
    statusDiv = document.getElementById('status');
    messageCount = document.getElementById('messageCount');
    sessionInfo = document.getElementById('sessionInfo');
    tokenInfo = document.getElementById('tokenInfo');
    protocolInfo = document.getElementById('protocolInfo');
    imageUpload = document.getElementById('imageUpload');
    imagePreviewContainer = document.getElementById('imagePreviewContainer');
    uploadButton = document.getElementById('uploadButton');
    documentUpload = document.getElementById('documentUpload');
    documentPreviewContainer = document.getElementById('documentPreviewContainer');
    documentUploadButton = document.getElementById('documentUploadButton');
    speechToggle = document.getElementById('speechToggle');
}

// ============================================================
// Utility Functions
// ============================================================

function imageToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

function addImagePreview(base64) {
    const previewDiv = document.createElement('div');
    previewDiv.className = 'image-preview';

    const img = document.createElement('img');
    img.src = base64;

    const removeBtn = document.createElement('button');
    removeBtn.className = 'image-preview-remove';
    removeBtn.textContent = '×';
    removeBtn.onclick = () => {
        const index = attachedImages.indexOf(base64);
        if (index > -1) {
            attachedImages.splice(index, 1);
        }
        previewDiv.remove();
    };

    previewDiv.appendChild(img);
    previewDiv.appendChild(removeBtn);
    imagePreviewContainer.appendChild(previewDiv);
}

function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function getDocumentIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        'pdf': '📕',
        'docx': '📘',
        'doc': '📘',
        'odt': '📗',
        'txt': '📄',
        'md': '📝'
    };
    return icons[ext] || '📄';
}

function addDocumentPreview(doc) {
    const previewDiv = document.createElement('div');
    previewDiv.className = 'document-preview';

    const icon = document.createElement('span');
    icon.className = 'document-preview-icon';
    icon.textContent = getDocumentIcon(doc.filename);

    const info = document.createElement('div');
    info.className = 'document-preview-info';

    const name = document.createElement('span');
    name.className = 'document-preview-name';
    name.textContent = doc.filename;
    name.title = doc.filename;

    const size = document.createElement('span');
    size.className = 'document-preview-size';
    size.textContent = formatFileSize(doc.size);

    info.appendChild(name);
    info.appendChild(size);

    const removeBtn = document.createElement('button');
    removeBtn.className = 'document-preview-remove';
    removeBtn.textContent = '×';
    removeBtn.onclick = () => {
        const index = attachedDocuments.findIndex(d => d.filename === doc.filename && d.content === doc.content);
        if (index > -1) {
            attachedDocuments.splice(index, 1);
        }
        previewDiv.remove();
    };

    previewDiv.appendChild(icon);
    previewDiv.appendChild(info);
    previewDiv.appendChild(removeBtn);
    documentPreviewContainer.appendChild(previewDiv);
}

function updateTokenDisplay(tokens) {
    if (!tokens) return;

    const total = tokens.total || 0;
    const max = tokens.max || 32768;
    const percentage = tokens.percentage || 0;

    const totalFormatted = total.toLocaleString();
    const maxFormatted = max.toLocaleString();

    let color = '#03dac6';
    if (percentage > 80) {
        color = '#ff4444';
    } else if (percentage > 60) {
        color = '#FF9800';
    } else if (percentage > 40) {
        color = '#FFEB3B';
    }

    tokenInfo.textContent = `Tokens: ${totalFormatted}/${maxFormatted} (${percentage}%)`;
    tokenInfo.style.color = color;
}

async function updateProtocolStatus() {
    try {
        const response = await fetch('/api/protocols/status/active');
        const protocolStatus = await response.json();

        if (protocolStatus && protocolStatus.success) {
            const protocol = protocolStatus.active_protocol;
            const isDefault = protocolStatus.is_default;
            const isProtected = protocolStatus.passphrase_protected;

            let display = `Protocol: ${protocol}`;
            if (isProtected) {
                display += ' 🔒';
            }

            if (isDefault) {
                protocolInfo.style.color = '#4CAF50';
            } else {
                protocolInfo.style.color = '#FF9800';
            }

            protocolInfo.textContent = display;
            console.log(`[Protocol Status] Updated: ${protocol}${isProtected ? ' 🔒' : ''}`);
        } else {
            console.warn('[Protocol Status] API returned error, defaulting to Default');
            protocolInfo.textContent = 'Protocol: Default';
            protocolInfo.style.color = '#4CAF50';
        }
    } catch (error) {
        console.error('[Protocol Status] Failed to fetch:', error);
        protocolInfo.textContent = 'Protocol: Default';
        protocolInfo.style.color = '#4CAF50';
    }
}

function redactPassphrases(text) {
    if (!text) return text;

    text = text.replace(
        /(passphrase\s+["'])([^"']+)(["'])/gi,
        '$1***REDACTED***$3'
    );

    text = text.replace(
        /(with\s+passphrase\s+["'])([^"']+)(["'])/gi,
        '$1***REDACTED***$3'
    );
    text = text.replace(
        /(using\s+passphrase\s+["'])([^"']+)(["'])/gi,
        '$1***REDACTED***$3'
    );

    text = text.replace(
        /(passphrase:\s*)(\S+)/gi,
        '$1***REDACTED***'
    );

    return text;
}

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function autoExpandTextarea() {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 192) + 'px';
}

function addCopyButtonsToCodeBlocks(container) {
    const codeBlocks = container.querySelectorAll('pre code');

    codeBlocks.forEach((codeBlock) => {
        const pre = codeBlock.parentElement;

        if (pre.querySelector('.code-copy-button')) {
            return;
        }

        const button = document.createElement('button');
        button.className = 'code-copy-button';
        button.innerHTML = '<span>📋</span><span>Copy</span>';

        button.addEventListener('click', async () => {
            const code = codeBlock.textContent;

            try {
                await navigator.clipboard.writeText(code);

                button.innerHTML = '<span>✓</span><span>Copied!</span>';
                button.classList.add('copied');

                setTimeout(() => {
                    button.innerHTML = '<span>📋</span><span>Copy</span>';
                    button.classList.remove('copied');
                }, 2000);
            } catch (err) {
                console.error('Failed to copy:', err);
                button.innerHTML = '<span>✗</span><span>Failed</span>';
                setTimeout(() => {
                    button.innerHTML = '<span>📋</span><span>Copy</span>';
                }, 2000);
            }
        });

        pre.appendChild(button);
    });
}

// ============================================================
// Message Creation
// ============================================================

function createToolStatus(icon, toolName) {
    const statusDiv = document.createElement('div');
    statusDiv.className = 'tool-status';

    const iconSpan = document.createElement('span');
    iconSpan.className = 'tool-status-icon';
    iconSpan.textContent = icon;

    const textSpan = document.createElement('span');
    textSpan.className = 'tool-status-text';
    textSpan.textContent = `${toolName} working...`;

    statusDiv.appendChild(iconSpan);
    statusDiv.appendChild(textSpan);
    return statusDiv;
}

function createMessage(role, content, images, contextLevel) {
    images = images || [];
    contextLevel = contextLevel || null;

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    if (role === 'user') {
        avatar.textContent = 'V';
    } else if (role === 'assistant') {
        avatar.textContent = 'I';

        if (contextLevel) {
            const badge = document.createElement('div');
            badge.className = 'context-tier-badge';

            if (contextLevel === 'TASK') {
                badge.textContent = '🔧';
                badge.classList.add('tier-task');
                badge.title = 'Task Mode (~3,500 tokens)';
            } else if (contextLevel === 'CONVERSATIONAL') {
                badge.textContent = '💬';
                badge.classList.add('tier-conversational');
                badge.title = 'Conversational Mode (~5,500 tokens)';
            } else if (contextLevel === 'DEEP') {
                badge.textContent = '🧠';
                badge.classList.add('tier-deep');
                badge.title = 'Deep Mode (~22,000 tokens)';
            } else {
                badge.textContent = '⚡';
                badge.classList.add('tier-conversational');
                badge.title = 'Full Context Mode';
            }

            avatar.appendChild(badge);
        }
    } else if (role === 'system') {
        avatar.textContent = '•';
    }

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    if (images && images.length > 0) {
        const imagesContainer = document.createElement('div');
        imagesContainer.style.display = 'flex';
        imagesContainer.style.gap = '0.5rem';
        imagesContainer.style.marginBottom = content ? '0.5rem' : '0';
        imagesContainer.style.flexWrap = 'wrap';

        images.forEach(imgData => {
            const img = document.createElement('img');
            img.src = imgData;
            img.style.maxWidth = '100%';
            img.style.maxHeight = '400px';
            img.style.borderRadius = '0.5rem';
            img.style.objectFit = 'contain';
            img.style.border = '1px solid #3a3a3a';
            img.style.cursor = 'pointer';
            img.title = 'Click to view full size';

            img.onclick = () => {
                const win = window.open();
                win.document.write(`<img src="${img.src}" style="max-width: 100%;">`);
                win.document.title = 'Generated Image';
            };

            imagesContainer.appendChild(img);
        });

        contentDiv.appendChild(imagesContainer);
    }

    if (content) {
        const redactedContent = redactPassphrases(content);

        const textSpan = document.createElement('span');
        textSpan.className = 'active-text';
        let parsedHtml = marked.parse(redactedContent);
        parsedHtml = parsedHtml.replace(/&lt;font color="([^"]+)"&gt;/gi, '<span style="color: $1">');
        parsedHtml = parsedHtml.replace(/&lt;\/font&gt;/gi, '</span>');
        parsedHtml = parsedHtml.replace(/<font color="([^"]+)">/gi, '<span style="color: $1">');
        parsedHtml = parsedHtml.replace(/<\/font>/gi, '</span>');
        textSpan.innerHTML = parsedHtml;

        addCopyButtonsToCodeBlocks(textSpan);

        contentDiv.appendChild(textSpan);
    }

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(contentDiv);
    return messageDiv;
}

// ============================================================
// Conversation History
// ============================================================

async function loadConversationHistory() {
    try {
        statusDiv.textContent = 'Loading conversation history...';
        statusDiv.className = 'status loading';

        const response = await fetch('/api/conversation/context');
        const data = await response.json();

        if (data.messages && data.messages.length > 0) {
            const conversationMessages = data.messages.slice(1);

            let pendingToolImages = [];

            conversationMessages.forEach((msg, index) => {
                if (msg.role === 'tool' && msg.images && Array.isArray(msg.images)) {
                    pendingToolImages.push(...msg.images);
                    console.log(`[History] Found ${msg.images.length} image(s) from tool: ${msg.tool_name || 'unknown'}`);
                }

                if (msg.role === 'user' || msg.role === 'assistant') {
                    let images = [];
                    if (msg.images && Array.isArray(msg.images)) {
                        images = msg.images;
                    }

                    if (msg.role === 'assistant' && pendingToolImages.length > 0) {
                        images = [...pendingToolImages, ...images];
                        console.log(`[History] Attaching ${pendingToolImages.length} tool image(s) to assistant message`);
                        pendingToolImages = [];
                    }

                    const messageDiv = createMessage(msg.role, msg.content, images);
                    messageDiv.style.animation = 'none';
                    chatContainer.appendChild(messageDiv);
                }
            });

            if (conversationMessages.length > 0) {
                const separator = createMessage('system', '─── Conversation continues ───');
                separator.style.animation = 'none';
                chatContainer.appendChild(separator);
            }

            scrollToBottom();
            console.log(`Loaded ${conversationMessages.length} messages from history`);
        }

        messageCount.textContent = `Messages: ${data.message_count || 0}`;
        if (data.session_id) {
            sessionInfo.textContent = `Session: ${data.session_id.substring(0, 8)}...`;
        }

        // Update token display from context data
        if (data.total_tokens !== undefined && data.context_window) {
            updateTokenDisplay({
                total: data.total_tokens,
                max: data.context_window,
                percentage: Math.round((data.total_tokens / data.context_window) * 100 * 10) / 10
            });
        }

        statusDiv.textContent = '';
        statusDiv.className = 'status';

    } catch (error) {
        console.error('Failed to load history:', error);
        statusDiv.textContent = 'Failed to load history';
        statusDiv.className = 'status';
    }
}

// ============================================================
// WebSocket Communication
// ============================================================

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);

    ws.onopen = () => {
        statusDiv.textContent = 'Connected';
        statusDiv.className = 'status connected';
        messageInput.disabled = false;
        sendButton.disabled = false;
        messageInput.focus();

        let mode = 'text';
        if (speechToggle.checked) {
            mode = (ttsQueue.videoSessionId && ttsQueue.videoPlayerOpen) ? 'video' : 'audio';
        }
        ws.send(JSON.stringify({
            type: 'set_output_mode',
            mode: mode
        }));
        console.log('[WS] Sent initial output mode:', mode);

        // Send initial video quality
        const qualitySelect = document.getElementById('pipQualitySelect');
        if (qualitySelect) {
            ws.send(JSON.stringify({
                type: 'set_video_quality',
                quality: qualitySelect.value
            }));
            console.log('[WS] Sent initial video quality:', qualitySelect.value);
        }
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };

    ws.onerror = () => {
        statusDiv.textContent = 'Connection error';
        statusDiv.className = 'status';
    };

    ws.onclose = () => {
        statusDiv.textContent = 'Disconnected - Reconnecting...';
        statusDiv.className = 'status';
        messageInput.disabled = true;
        sendButton.disabled = true;
        setTimeout(connectWebSocket, 2000);
    };
}

function handleWebSocketMessage(data) {
    switch(data.type) {
        case 'start':
            isStreaming = true;
            sendButton.disabled = true;
            sendButton.style.display = 'none';
            stopButton.style.display = 'block';
            currentAssistantText = '';
            currentThinkingContent = '';
            ttsQueue.reset();

            if (typeof pipPlayer !== 'undefined' && pipPlayer.hlsInitialized && !ttsQueue.serverSideRoutingEnabled) {
                console.log('[HLS] Resetting for new message (browser-side routing)');
                pipPlayer.cleanupHLS();
            } else if (typeof pipPlayer !== 'undefined' && pipPlayer.hlsInitialized && ttsQueue.serverSideRoutingEnabled) {
                console.log('[HLS] Server-side routing active - waiting for hls_new_turn');
            }

            currentContextLevel = data.context_level || 'FULL';
            console.log(`[Context Tier] ${currentContextLevel}`);

            currentAssistantMessage = createMessage('assistant', 'Iris is thinking...', [], currentContextLevel);
            chatContainer.appendChild(currentAssistantMessage);
            scrollToBottom();

            if (data.tokens) {
                updateTokenDisplay(data.tokens);
            }
            break;

        case 'tool_start':
            console.log(`Using ${data.tool_count} tool(s)`);
            break;

        case 'tool_marker_start':
            console.log(`Tool marker start: ${data.tool_count} tool(s) in iteration ${data.iteration}`);
            break;

        case 'tool_marker_end':
            console.log('Tool marker end');
            currentAssistantText = '';
            if (currentAssistantMessage) {
                const activeSpan = currentAssistantMessage.querySelector('span.active-text');
                if (activeSpan) {
                    activeSpan.classList.remove('active-text');
                }
            }
            scrollToBottom();
            break;

        case 'kv_cache_metrics':
            lastKvCacheMetrics = {
                cached: data.cache_tokens,
                new: data.prompt_tokens,
                total: data.total_tokens,
                efficiency: data.efficiency,
                genTokPerSec: data.gen_tok_per_sec || 0,
                promptTokPerSec: data.prompt_tok_per_sec || 0,
                predictedN: data.predicted_n || 0,
                totalMs: data.total_ms || 0
            };
            console.log(`[Perf] KV: ${data.efficiency}% | Gen: ${data.gen_tok_per_sec} tok/s | Prompt: ${data.prompt_tok_per_sec} tok/s`);
            break;

        case 'tool_executing':
            {
                const toolIcon = data.tool_icon || '🔧';
                const toolName = data.tool_name || 'tool';
                const toolStatus = createToolStatus(toolIcon, toolName);

                if (currentAssistantMessage) {
                    const content = currentAssistantMessage.querySelector('.message-content');
                    content.appendChild(toolStatus);
                    scrollToBottom();
                }
            }
            break;

        case 'tool_result':
            if (currentAssistantMessage) {
                const messageContent = currentAssistantMessage.querySelector('.message-content');
                const lastToolStatus = messageContent.querySelector('.tool-status:last-of-type');

                if (lastToolStatus) {
                    const statusText = lastToolStatus.querySelector('.tool-status-text');
                    const icon = lastToolStatus.querySelector('.tool-status-icon');

                    if (data.success) {
                        statusText.textContent = `${data.tool_name} ✓`;
                        statusText.style.color = '#03dac6';
                        icon.style.animation = 'none';
                    } else {
                        statusText.textContent = `${data.tool_name} failed: ${data.error}`;
                        statusText.style.color = '#ff4444';
                        icon.style.animation = 'none';
                    }
                }
            }
            break;

        case 'thinking_start':
            if (currentAssistantMessage) {
                currentThinkingContent = '';
                const msgContent = currentAssistantMessage.querySelector('.message-content');
                const details = document.createElement('details');
                details.className = 'thinking-block';
                const summary = document.createElement('summary');
                summary.textContent = 'Thinking...';
                const thinkDiv = document.createElement('div');
                thinkDiv.className = 'thinking-content';
                details.appendChild(summary);
                details.appendChild(thinkDiv);
                // Insert at top of bubble (before active-text span)
                msgContent.insertBefore(details, msgContent.firstChild);
                scrollToBottom();
            }
            break;

        case 'thinking_chunk':
            if (currentAssistantMessage) {
                currentThinkingContent += data.content;
                const tcDiv = currentAssistantMessage.querySelector('.thinking-content');
                if (tcDiv) {
                    tcDiv.textContent = currentThinkingContent;
                }
                const tcSummary = currentAssistantMessage.querySelector('.thinking-block summary');
                if (tcSummary) {
                    const wordCount = currentThinkingContent.split(/\s+/).filter(w => w).length;
                    tcSummary.textContent = `Thinking... (${wordCount} words)`;
                }
                scrollToBottom();
            }
            break;

        case 'thinking_end':
            if (currentAssistantMessage) {
                const thinkBlock = currentAssistantMessage.querySelector('.thinking-block');
                if (thinkBlock) {
                    const teSummary = thinkBlock.querySelector('summary');
                    const teWordCount = currentThinkingContent.split(/\s+/).filter(w => w).length;
                    teSummary.textContent = `Thought for ${teWordCount} words`;
                    thinkBlock.removeAttribute('open');
                }
                currentThinkingContent = '';
            }
            break;

        case 'chunk':
            if (currentAssistantMessage) {
                currentAssistantText += data.content;

                if (!ttsQueue.serverSideRoutingEnabled) {
                    ttsQueue.addTextChunk(data.content);
                }

                const content = currentAssistantMessage.querySelector('.message-content');
                let textSpan = content.querySelector('span.active-text');
                if (!textSpan) {
                    textSpan = document.createElement('span');
                    textSpan.className = 'active-text';
                    content.appendChild(textSpan);
                }

                let parsedHtml = marked.parse(currentAssistantText);
                parsedHtml = parsedHtml.replace(/&lt;font color="([^"]+)"&gt;/gi, '<span style="color: $1">');
                parsedHtml = parsedHtml.replace(/&lt;\/font&gt;/gi, '</span>');
                parsedHtml = parsedHtml.replace(/<font color="([^"]+)">/gi, '<span style="color: $1">');
                parsedHtml = parsedHtml.replace(/<\/font>/gi, '</span>');
                textSpan.innerHTML = parsedHtml;

                addCopyButtonsToCodeBlocks(textSpan);
                scrollToBottom();
            }
            break;

        case 'interrupted':
            isStreaming = false;
            sendButton.disabled = false;
            sendButton.style.display = 'block';
            stopButton.style.display = 'none';
            stopButton.disabled = false;
            stopButton.textContent = '⏹ Stop';
            if (!ttsQueue.serverSideRoutingEnabled) {
                ttsQueue.finalize();
            }

            {
                const interruptMsg = createMessage('system', '⏹ Generation stopped by user');
                chatContainer.appendChild(interruptMsg);
                scrollToBottom();
            }

            currentAssistantMessage = null;
            currentAssistantText = '';
            currentContextLevel = null;
            messageInput.focus();
            break;

        case 'done':
            isStreaming = false;
            sendButton.disabled = false;
            sendButton.style.display = 'block';
            stopButton.style.display = 'none';
            if (!ttsQueue.serverSideRoutingEnabled) {
                ttsQueue.finalize();
            }

            if (typeof pipPlayer !== 'undefined' && pipPlayer.useHLS) {
                pipPlayer.finalizeHLSStream();
            }

            if (lastKvCacheMetrics && currentAssistantMessage) {
                const messageContent = currentAssistantMessage.querySelector('.message-content');
                if (messageContent) {
                    const statsDiv = document.createElement('div');
                    statsDiv.className = 'kv-cache-stats';
                    const effClass = lastKvCacheMetrics.efficiency >= 80 ? 'excellent' :
                                    lastKvCacheMetrics.efficiency >= 65 ? 'good' :
                                    lastKvCacheMetrics.efficiency >= 50 ? 'fair' : 'poor';
                    const speedClass = lastKvCacheMetrics.genTokPerSec >= 40 ? 'fast' :
                                       lastKvCacheMetrics.genTokPerSec >= 20 ? 'normal' : 'slow';

                    let statsHtml = `<span class="kv-label">KV Cache:</span> ` +
                        `<span class="kv-cached">${lastKvCacheMetrics.cached.toLocaleString()}</span> cached + ` +
                        `<span class="kv-new">${lastKvCacheMetrics.new.toLocaleString()}</span> new ` +
                        `<span class="kv-efficiency ${effClass}">(${lastKvCacheMetrics.efficiency}% hit)</span>`;

                    if (lastKvCacheMetrics.genTokPerSec > 0) {
                        statsHtml += `<span class="stat-sep">|</span>` +
                            `<span class="speed-label">Generate:</span> ` +
                            `<span class="speed-val ${speedClass}">${lastKvCacheMetrics.genTokPerSec} t/s</span>`;
                        if (lastKvCacheMetrics.predictedN > 0) {
                            statsHtml += ` <span class="kv-total">(${lastKvCacheMetrics.predictedN} tokens)</span>`;
                        }
                    }

                    if (lastKvCacheMetrics.promptTokPerSec > 0) {
                        const promptSpeedClass = lastKvCacheMetrics.promptTokPerSec >= 1000 ? 'fast' :
                                                lastKvCacheMetrics.promptTokPerSec >= 500 ? 'normal' : 'slow';
                        statsHtml += `<span class="stat-sep">|</span>` +
                            `<span class="speed-label">Prompt:</span> ` +
                            `<span class="speed-val ${promptSpeedClass}">${Math.round(lastKvCacheMetrics.promptTokPerSec)} t/s</span>`;
                    }

                    statsDiv.innerHTML = statsHtml;
                    messageContent.appendChild(statsDiv);
                }
                lastKvCacheMetrics = null;
            }

            currentAssistantMessage = null;
            currentAssistantText = '';
            currentContextLevel = null;
            messageCount.textContent = `Messages: ${data.message_count}`;

            if (data.tokens) {
                updateTokenDisplay(data.tokens);
            }

            messageInput.focus();
            break;

        case 'mode_set':
            console.log('[WS] Mode set by server:', data.mode, 'server_side_routing:', data.server_side_routing);
            ttsQueue.setServerSideRouting(data.server_side_routing || false);

            {
                let hasServerSession = false;
                if (data.video_session_id) {
                    ttsQueue.videoSessionId = data.video_session_id;
                    ttsQueue.videoPlayerOpen = true;
                    console.log('[WS] Video session started:', data.video_session_id);

                    if (typeof pipPlayer !== 'undefined') {
                        pipPlayer.sessionId = data.video_session_id;
                        pipPlayer.isActive = true;
                        pipPlayer.videoQueue = [];
                        pipPlayer.currentChunkIndex = 0;
                        pipPlayer.isPlaying = false;
                        pipPlayer._playingTransition = false;
                        pipPlayer._lastProcessedEndedChunk = -1;
                        pipPlayer.useHLS = true;

                        if (pipPlayer.hls) {
                            pipPlayer.hls.destroy();
                            pipPlayer.hls = null;
                        }

                        pipPlayer.hlsInitialized = false;
                        pipPlayer._hlsPlaylistLoaded = false;
                        pipPlayer.show();
                        pipPlayer.statusElement.textContent = 'Ready - HLS Streaming';

                        const playlistUrl = `/api/video/hls/${data.video_session_id}/playlist.m3u8`;
                        pipPlayer.initHLSPlayback(playlistUrl);

                        console.log('[PiP] Activated with HLS session:', data.video_session_id);
                        hasServerSession = true;
                    }
                }

                if (typeof pipPlayer !== 'undefined' && pipPlayer._modeSetResolver) {
                    pipPlayer._modeSetResolver(hasServerSession);
                }
            }
            break;

        case 'audio_chunk':
            console.log('[WS] Audio chunk received from server');
            ttsQueue.handleAudioChunk(data);
            break;

        case 'video_chunk_ready':
            console.log('[WS] Video chunk ready from server');
            ttsQueue.handleVideoChunkReady(data);
            break;

        case 'ui_notification':
            {
                const notifDiv = document.createElement('div');
                notifDiv.className = `message notification ${data.style || 'info'}`;

                const notifAvatar = document.createElement('div');
                notifAvatar.className = 'message-avatar';
                const notifIcons = { info: 'i', success: '✓', warning: '⚠', error: '✗' };
                notifAvatar.textContent = notifIcons[data.style] || 'i';

                const notifContent = document.createElement('div');
                notifContent.className = 'message-content';
                notifContent.textContent = data.message;

                notifDiv.appendChild(notifAvatar);
                notifDiv.appendChild(notifContent);
                chatContainer.appendChild(notifDiv);
                scrollToBottom();
            }
            break;

        case 'tool_image':
            console.log('[WS] Tool generated image:', data.tool_name, data.filename);

            if (currentAssistantMessage) {
                const content = currentAssistantMessage.querySelector('.message-content');

                const imgContainer = document.createElement('div');
                imgContainer.className = 'tool-generated-image';
                imgContainer.style.cssText = 'margin: 0.5rem 0; max-width: 100%;';

                const img = document.createElement('img');
                img.src = `data:image/png;base64,${data.image_base64}`;
                img.alt = data.filename || 'Generated image';
                img.style.cssText = 'max-width: 100%; border-radius: 0.5rem; cursor: pointer;';
                img.title = 'Click to view full size';

                img.onclick = () => {
                    const win = window.open();
                    win.document.write(`<img src="${img.src}" style="max-width: 100%;">`);
                    win.document.title = data.filename || 'Generated Image';
                };

                imgContainer.appendChild(img);
                content.appendChild(imgContainer);
                scrollToBottom();
            }
            break;

        case 'hls_segment_ready':
            console.log('[WS] HLS segment ready:', data);
            if (typeof pipPlayer !== 'undefined' && pipPlayer.sessionId === data.session_id) {
                pipPlayer.onHLSSegmentReady(data);
            }
            break;

        case 'hls_new_turn':
            console.log('[WS] HLS new turn:', data);
            if (typeof pipPlayer !== 'undefined' && pipPlayer.sessionId === data.session_id) {
                pipPlayer.onHLSNewTurn(data);
            }
            break;

        case 'hls_stream_complete':
            console.log('[WS] HLS stream complete:', data);
            if (typeof pipPlayer !== 'undefined' && pipPlayer.sessionId === data.session_id) {
                pipPlayer.onHLSStreamComplete(data);
            }
            break;

        case 'protocol_status':
            console.log('[WS] Protocol status:', data);
            {
                const protocol = data.active_protocol;
                const isDefault = data.is_default;

                protocolInfo.textContent = `Protocol: ${protocol}`;

                if (isDefault) {
                    protocolInfo.style.color = '#4CAF50';
                } else {
                    protocolInfo.style.color = '#FF9800';
                }
            }
            break;

        case 'error':
            statusDiv.textContent = `Error: ${data.content}`;
            statusDiv.className = 'status';
            isStreaming = false;
            sendButton.disabled = false;
            sendButton.style.display = 'block';
            stopButton.style.display = 'none';
            break;
    }
}

// ============================================================
// User Input Handling
// ============================================================

function sendMessage() {
    if (isStreaming || !ws || ws.readyState !== WebSocket.OPEN) return;

    const message = messageInput.value.trim();
    if (!message && attachedImages.length === 0 && attachedDocuments.length === 0) return;

    const thinkingToggle = document.getElementById('thinkingToggle');
    const thinkingEnabled = thinkingToggle.checked;

    const userMsgDiv = createMessage('user', message || '', attachedImages);
    chatContainer.appendChild(userMsgDiv);
    scrollToBottom();

    if (typeof pipPlayer !== 'undefined' && pipPlayer.isActive) {
        pipPlayer.showThinking();
    }

    const payload = {
        message: message || (attachedImages.length > 0 ? '(attached image)' : '(attached document)'),
        images: attachedImages.length > 0 ? attachedImages : undefined,
        documents: attachedDocuments.length > 0 ? attachedDocuments : undefined,
        sender: 'user',
        thinking: thinkingEnabled
    };

    console.log(`Sending message with ${attachedImages.length} image(s), ${attachedDocuments.length} document(s), thinking: ${thinkingEnabled}`);
    ws.send(JSON.stringify(payload));

    messageInput.value = '';
    messageInput.style.height = 'auto';
    attachedImages = [];
    attachedDocuments = [];
    imagePreviewContainer.innerHTML = '';
    documentPreviewContainer.innerHTML = '';
}

// ============================================================
// Webcam Handling
// ============================================================

let webcamStream = null;
let webcamInterval = null;
let webcamToggle, webcamPreview, webcamPreviewVideo, webcamPreviewStatus, webcamPreviewClose, webcamPreviewHeader;

function initWebcamElements() {
    webcamToggle = document.getElementById('webcamToggle');
    webcamPreview = document.getElementById('webcamPreview');
    webcamPreviewVideo = document.getElementById('webcamPreviewVideo');
    webcamPreviewStatus = document.getElementById('webcamPreviewStatus');
    webcamPreviewClose = document.getElementById('webcamPreviewClose');
    webcamPreviewHeader = document.getElementById('webcamPreviewHeader');
}

async function startWebcam() {
    try {
        console.log('[Webcam] Starting webcam...');
        webcamStream = await navigator.mediaDevices.getUserMedia({
            video: { width: 640, height: 480 }
        });
        console.log('[Webcam] ✓ Webcam started');

        webcamPreviewVideo.srcObject = webcamStream;
        webcamPreview.classList.add('active');
        webcamPreviewStatus.textContent = 'Streaming (frames sent every 2.5s)';
        webcamPreviewStatus.classList.add('streaming');

        webcamInterval = setInterval(async () => {
            try {
                const frame = await captureWebcamFrame();
                await sendFrameToServer(frame);
            } catch (err) {
                console.error('[Webcam] Error capturing/sending frame:', err);
            }
        }, 2500);

        const frame = await captureWebcamFrame();
        await sendFrameToServer(frame);
    } catch (err) {
        console.error('[Webcam] Error starting webcam:', err);
        alert('Could not access webcam: ' + err.message);
        webcamToggle.checked = false;
    }
}

function stopWebcam() {
    console.log('[Webcam] Stopping webcam...');
    if (webcamInterval) {
        clearInterval(webcamInterval);
        webcamInterval = null;
    }
    if (webcamStream) {
        webcamStream.getTracks().forEach(track => track.stop());
        webcamStream = null;
    }
    webcamPreviewVideo.srcObject = null;
    webcamPreview.classList.remove('active');
    webcamPreviewStatus.textContent = 'Waiting for webcam...';
    webcamPreviewStatus.classList.remove('streaming');
    console.log('[Webcam] ✓ Webcam stopped');
}

async function captureWebcamFrame() {
    const video = webcamPreviewVideo;

    if (video.readyState < 2) {
        await new Promise(resolve => {
            video.onloadeddata = () => resolve();
        });
    }

    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0);

    return canvas.toDataURL('image/jpeg', 0.8);
}

async function sendFrameToServer(frameData) {
    try {
        const response = await fetch('/api/faces/webcam_frame', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ frame: frameData })
        });

        if (!response.ok) {
            console.error('[Webcam] Server error:', response.statusText);
        }
    } catch (err) {
        console.error('[Webcam] Error sending frame:', err);
    }
}

function initWebcamDraggable() {
    let webcamDragging = false;
    let webcamDragOffsetX = 0;
    let webcamDragOffsetY = 0;

    webcamPreviewHeader.addEventListener('mousedown', (e) => {
        webcamDragging = true;
        webcamDragOffsetX = e.clientX - webcamPreview.offsetLeft;
        webcamDragOffsetY = e.clientY - webcamPreview.offsetTop;
        webcamPreview.style.cursor = 'grabbing';
    });

    document.addEventListener('mousemove', (e) => {
        if (webcamDragging) {
            webcamPreview.style.left = (e.clientX - webcamDragOffsetX) + 'px';
            webcamPreview.style.top = (e.clientY - webcamDragOffsetY) + 'px';
        }
    });

    document.addEventListener('mouseup', () => {
        webcamDragging = false;
        webcamPreview.style.cursor = '';
    });
}

// ============================================================
// Event Listeners Setup
// ============================================================

function setupEventListeners() {
    uploadButton.addEventListener('click', () => {
        imageUpload.click();
    });

    imageUpload.addEventListener('change', async (e) => {
        const files = Array.from(e.target.files);

        for (const file of files) {
            if (file.type.startsWith('image/')) {
                const base64 = await imageToBase64(file);
                attachedImages.push(base64);
                addImagePreview(base64);
            }
        }

        imageUpload.value = '';
    });

    // Document upload handlers
    documentUploadButton.addEventListener('click', () => {
        documentUpload.click();
    });

    documentUpload.addEventListener('change', async (e) => {
        const files = Array.from(e.target.files);

        for (const file of files) {
            const base64 = await fileToBase64(file);
            attachedDocuments.push({
                content: base64,
                filename: file.name,
                size: file.size
            });
            addDocumentPreview({
                content: base64,
                filename: file.name,
                size: file.size
            });
        }

        documentUpload.value = '';
    });

    messageInput.addEventListener('paste', async (e) => {
        const items = Array.from(e.clipboardData.items);

        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                const base64 = await imageToBase64(file);
                attachedImages.push(base64);
                addImagePreview(base64);
            }
        }
    });

    messageInput.addEventListener('input', autoExpandTextarea);

    stopButton.addEventListener('click', () => {
        if (isStreaming && ws && ws.readyState === WebSocket.OPEN) {
            console.log('[Stop] Sending interrupt request');
            ws.send(JSON.stringify({ type: 'interrupt' }));

            stopButton.disabled = true;
            stopButton.textContent = '⏹ Stopping...';
        }
    });

    sendButton.addEventListener('click', sendMessage);
    messageInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    speechToggle.addEventListener('change', (e) => {
        if (e.target.checked) {
            ttsQueue.enable();
        } else {
            ttsQueue.disable();
        }

        if (ws && ws.readyState === WebSocket.OPEN) {
            let mode = 'text';
            if (e.target.checked) {
                mode = (ttsQueue.videoSessionId && ttsQueue.videoPlayerOpen) ? 'video' : 'audio';
            }
            ws.send(JSON.stringify({
                type: 'set_output_mode',
                mode: mode
            }));
            console.log('[Speech] Sent output mode to server:', mode);
        }
    });

    // Video quality change - sync to server for bandwidth adaptation
    const pipQualitySelect = document.getElementById('pipQualitySelect');
    if (pipQualitySelect) {
        pipQualitySelect.addEventListener('change', (e) => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'set_video_quality',
                    quality: e.target.value
                }));
                console.log('[Video] Sent quality to server:', e.target.value);
            }
        });
    }

    webcamToggle.addEventListener('change', (e) => {
        if (e.target.checked) {
            startWebcam();
        } else {
            stopWebcam();
        }
    });

    webcamPreviewClose.addEventListener('click', () => {
        webcamToggle.checked = false;
        stopWebcam();
    });

    const thinkingToggle = document.getElementById('thinkingToggle');
    const savedThinkingState = localStorage.getItem('irisThinkingEnabled');
    if (savedThinkingState !== null) {
        thinkingToggle.checked = savedThinkingState === 'true';
    }
    thinkingToggle.addEventListener('change', (e) => {
        localStorage.setItem('irisThinkingEnabled', e.target.checked);
        console.log(`[Thinking] ${e.target.checked ? 'Enabled' : 'Disabled'}`);
    });

    window.addEventListener('voiceTranscript', async (event) => {
        console.log('[VOX Event] Received transcript event:', event.detail);
        const transcript = event.detail.transcript;

        const userMsgDiv = createMessage('user', transcript, []);
        chatContainer.appendChild(userMsgDiv);
        scrollToBottom();

        if (ws && ws.readyState === WebSocket.OPEN) {
            const thinkingToggle = document.getElementById('thinkingToggle');
            const thinkingEnabled = thinkingToggle ? thinkingToggle.checked : true;

            const payload = {
                message: transcript,
                sender: 'user',
                thinking: thinkingEnabled
            };
            ws.send(JSON.stringify(payload));
            console.log(`[VOX Event] Sent to WebSocket, thinking: ${thinkingEnabled}`);
        } else {
            console.error('[VOX Event] WebSocket not ready!');
        }
    });
}

// ============================================================
// Initialization
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    initDOMElements();
    initWebcamElements();

    ttsQueue = new TTSQueue();
    pipPlayer = new PiPVideoPlayer();

    initWebcamDraggable();

    setupEventListeners();

    loadConversationHistory().then(() => {
        connectWebSocket();
        updateProtocolStatus();
    });
});
