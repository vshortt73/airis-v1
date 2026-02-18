/**
 * PiPVideoPlayer - Picture-in-Picture Video Streaming Player
 * Supports HLS streaming, double-buffer playback, and idle/thinking video rotation
 *
 * Dependencies: HLS.js (loaded externally), ttsQueue (global)
 * Global instances: pipPlayer (created after DOM load)
 */

class PiPVideoPlayer {
    constructor() {
        this.container = document.getElementById('pipContainer');
        this.header = document.getElementById('pipHeader');
        // Double-buffer video elements for seamless transitions
        this.videoElementA = document.getElementById('pip-video-player');
        this.videoElementB = document.getElementById('pip-video-player-b');
        this.activePlayer = 'A';  // Track which player is currently showing
        this.loopElement = document.getElementById('pip-loop-video');
        this.thinkingElement = document.getElementById('pip-thinking-video');
        this.statusElement = document.getElementById('pipStatus');
        this.queueInfoElement = document.getElementById('pipQueueInfo');
        this.launchBtn = document.getElementById('pipLaunchBtn');

        this.sessionId = null;
        this.videoQueue = [];        // Queue of {blob, url, status} objects
        this.preloadedUrls = [];     // URLs ready to play
        this.currentChunkIndex = 0;
        this.isPlaying = false;
        this._playingTransition = false;  // Guard against multiple transitions
        this._lastProcessedEndedChunk = -1;  // Guard against double-processing ended events
        this._hlsPlaylistLoaded = false;  // Track if HLS playlist has been loaded
        this.pollInterval = null;
        this.isActive = false;
        this.poppedOut = false;      // True when session is transferred to pop-out window
        this.streamingMode = false;  // True when receiving stream
        this.abortController = null; // For canceling streams
        this.streamQueue = [];       // Queue of blob URLs for streaming
        this.streamIndex = 0;        // Current streaming segment
        this.textQueue = [];         // Queue of text to stream
        this._processingTextQueue = false;  // Flag for queue processing
        this._streamResolve = null;  // Resolve function for current stream

        // Video quality setting: 'high' (2Mbps), 'medium' (1Mbps), 'low' (500kbps)
        // Lower quality = smaller files = faster download on slow connections
        this.videoQuality = 'high';

        // HLS streaming (replaces double-buffer approach)
        this.hls = null;
        this.useHLS = true;  // Use HLS by default
        this.hlsInitialized = false;
        this.hlsTextQueue = [];  // Queue of text for HLS generation
        this._hlsProcessing = false;
        this._hlsStreamEnded = false;  // Set true when no more text is coming

        // Video library support (idle rotation + thinking videos)
        this.idleVideos = [];           // Array of idle video URLs
        this.thinkingVideos = [];       // Array of thinking video URLs
        this.idleRotationTimer = null;  // Timer for switching idle videos
        this.currentThinkingVideo = null; // Thinking video for current call
        this.hasThinkingVideo = false;
        this.idleRotationActive = false;

        // Load video library from API
        this.loadVideoLibrary();

        this.initDraggable();
        this.initControls();
        this.initBroadcastListener();
    }

    async loadVideoLibrary() {
        // Fetch available videos from API
        try {
            const response = await fetch('/api/ui-videos');
            if (response.ok) {
                const data = await response.json();
                this.idleVideos = data.idle || [];
                this.thinkingVideos = data.thinking || [];

                console.log(`[PiP] Video library loaded: ${this.idleVideos.length} idle, ${this.thinkingVideos.length} thinking`);

                // Set up thinking video support
                if (this.thinkingVideos.length > 0) {
                    this.hasThinkingVideo = true;
                }

                // If we have idle videos, start rotation when active
                // (will be started by show() or activate methods)
            } else {
                console.log('[PiP] No video library found, using default loop.mp4');
            }
        } catch (e) {
            console.log('[PiP] Failed to load video library:', e);
        }
    }

    startIdleRotation() {
        // Start random idle video rotation
        if (this.idleVideos.length === 0) {
            // No idle videos, use default loop.mp4
            this.loopElement.src = '/static/loop.mp4';
            this.loopElement.loop = true;
            this.loopElement.play().catch(() => {});
            return;
        }

        if (this.idleRotationActive) return;
        this.idleRotationActive = true;

        const playRandomIdle = () => {
            if (!this.idleRotationActive || !this.isActive) return;

            // Pick random video
            const randomIndex = Math.floor(Math.random() * this.idleVideos.length);
            const videoUrl = this.idleVideos[randomIndex];

            // Set and play
            this.loopElement.src = videoUrl;
            this.loopElement.loop = true;
            this.loopElement.style.display = '';
            this.loopElement.play().catch(() => {});

            console.log(`[PiP] Playing idle video: ${videoUrl.split('/').pop()}`);

            // Schedule next switch (5-30 seconds)
            const duration = 5000 + Math.random() * 25000; // 5-30 seconds
            this.idleRotationTimer = setTimeout(playRandomIdle, duration);
        };

        playRandomIdle();
    }

    stopIdleRotation() {
        // Stop idle rotation (when streaming or thinking)
        this.idleRotationActive = false;
        if (this.idleRotationTimer) {
            clearTimeout(this.idleRotationTimer);
            this.idleRotationTimer = null;
        }
    }

    pickRandomThinkingVideo() {
        // Pick a random thinking video for this call
        if (this.thinkingVideos.length === 0) {
            this.currentThinkingVideo = null;
            return null;
        }

        const randomIndex = Math.floor(Math.random() * this.thinkingVideos.length);
        this.currentThinkingVideo = this.thinkingVideos[randomIndex];
        console.log(`[PiP] Selected thinking video: ${this.currentThinkingVideo.split('/').pop()}`);
        return this.currentThinkingVideo;
    }

    showThinking() {
        // Show thinking loop (or idle loop if no thinking video)
        if (!this.isActive) return;

        // Stop idle rotation
        this.stopIdleRotation();

        if (this.hasThinkingVideo && this.thinkingVideos.length > 0) {
            // Pick a random thinking video for this call (if not already picked)
            if (!this.currentThinkingVideo) {
                this.pickRandomThinkingVideo();
            }

            if (this.currentThinkingVideo) {
                this.loopElement.style.display = 'none';
                this.thinkingElement.src = this.currentThinkingVideo;
                this.thinkingElement.loop = true;
                this.thinkingElement.style.display = '';
                this.thinkingElement.play().catch(() => {});
                console.log('[PiP] Showing thinking loop');
                return;
            }
        }

        // Fall back to idle loop (but don't rotate during thinking)
        this.loopElement.style.display = '';
        this.loopElement.play().catch(() => {});
    }

    hideThinking() {
        // Hide thinking loop (caller decides whether to show idle or stream)
        this.thinkingElement.style.display = 'none';
        this.thinkingElement.pause();
        // Note: currentThinkingVideo is reset when stream ends (in showLoop)
        // not here, in case we need to re-show thinking during same call
    }

    initDraggable() {
        let isDragging = false;
        let startX, startY, initialX, initialY;

        this.header.addEventListener('mousedown', (e) => {
            if (e.target.tagName === 'BUTTON') return;
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            const rect = this.container.getBoundingClientRect();
            initialX = rect.left;
            initialY = rect.top;
            this.header.style.cursor = 'grabbing';
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;

            // Calculate new position
            let newX = initialX + dx;
            let newY = initialY + dy;

            // Keep within viewport
            const maxX = window.innerWidth - this.container.offsetWidth;
            const maxY = window.innerHeight - this.container.offsetHeight;
            newX = Math.max(0, Math.min(newX, maxX));
            newY = Math.max(0, Math.min(newY, maxY));

            this.container.style.left = newX + 'px';
            this.container.style.top = newY + 'px';
            this.container.style.right = 'auto';
        });

        document.addEventListener('mouseup', () => {
            isDragging = false;
            this.header.style.cursor = 'move';
        });
    }

    initControls() {
        // Close button
        document.getElementById('pipCloseBtn').addEventListener('click', () => {
            this.close();
        });

        // Pop-out button
        document.getElementById('pipPopoutBtn').addEventListener('click', () => {
            this.popOut();
        });

        // Playback controls
        document.getElementById('pipPrevBtn').addEventListener('click', () => {
            this.playPrevious();
        });

        document.getElementById('pipStopBtn').addEventListener('click', () => {
            this.stop();
        });

        document.getElementById('pipNextBtn').addEventListener('click', () => {
            this.playNext();
        });

        // Quality selector
        const qualitySelect = document.getElementById('pipQualitySelect');
        // Initialize from current dropdown value
        this.videoQuality = qualitySelect.value || 'high';
        console.log(`[PiP] Initial video quality: ${this.videoQuality}`);

        qualitySelect.addEventListener('change', (e) => {
            this.videoQuality = e.target.value;
            console.log(`[PiP] Video quality changed to: ${this.videoQuality}`);
            this.statusElement.textContent = `Quality: ${this.videoQuality.toUpperCase()}`;
            setTimeout(() => {
                if (!this.isPlaying) this.statusElement.textContent = 'Ready';
            }, 2000);
        });

        // Video ended event - both players (LEGACY chunk-based only)
        // Streaming playback handles its own 'ended' events via Promises
        const onVideoEnded = (event) => {
            // Skip if streaming is active - streaming has its own event handling
            if (this.streamQueue && this.streamQueue.length > 0) {
                console.log('[PiP] Ignoring legacy ended event - streaming mode active');
                return;
            }

            // Only respond to the ACTIVE player ending
            const { active } = this.getPlayers();
            if (event.target !== active) {
                console.log('[PiP] Ignoring ended event from inactive player');
                return;
            }

            // Guard against ended event during an ongoing transition
            if (this._playingTransition) {
                console.log('[PiP] WARNING: Video ended during transition - ignoring to prevent race');
                return;
            }

            // Guard against double-processing the same chunk's ended event
            if (this.currentChunkIndex === this._lastProcessedEndedChunk) {
                console.log('[PiP] WARNING: Double ended event for chunk', this.currentChunkIndex, '- ignoring');
                return;
            }
            this._lastProcessedEndedChunk = this.currentChunkIndex;

            const prevIndex = this.currentChunkIndex;
            this.currentChunkIndex++;
            // Keep isPlaying true until playNextChunk handles it
            // This prevents handleChunkReady from triggering a race

            console.log(`[PiP] Video ended (legacy). Chunk ${prevIndex} -> ${this.currentChunkIndex}. Queue:`,
                this.videoQueue.map(c => `${c.chunk_index}:${c.status}${c.preloaded ? '*' : ''}`).join(', '));

            this.playNextChunk();
        };
        // Store handler so we can remove it when switching to HLS mode
        this._legacyEndedHandler = onVideoEnded;
        this.videoElementA.addEventListener('ended', onVideoEnded);
        this.videoElementB.addEventListener('ended', onVideoEnded);

        // Launch button
        this.launchBtn.addEventListener('click', () => {
            this.launch();
        });
    }

    initBroadcastListener() {
        // Listen for in-page custom events from TTSQueue
        // (BroadcastChannel only works across different windows, not same page)
        window.addEventListener('iris-video-chunk', (event) => {
            if (!this.isActive) return;
            const detail = event.detail;
            console.log('[PiP] Received video chunk event:', detail);

            // Route based on status: 'completed' updates existing, 'queued' adds new
            if (detail.status === 'completed') {
                this.handleChunkReady(detail);
            } else {
                this.queueChunk(detail);
            }
        });

        // Also listen to BroadcastChannel for external window communication
        ttsQueue.videoChannel.addEventListener('message', (event) => {
            const { type, data } = event.data;

            // Pop-in recovery: pop-out window closed, re-activate PiP
            if (type === 'player-closed' && this.poppedOut) {
                console.log('[PiP] Pop-out closed, re-activating PiP');
                this.poppedOut = false;
                if (this.sessionId) {
                    // Re-attach HLS.js to PiP video element
                    if (this.hls) {
                        this.hls.attachMedia(this.videoElementA);
                        this.hls.startLoad();
                    }
                    this.show();
                    this.startIdleRotation();
                }
                return;
            }

            // Handle VOX pause/resume from pop-out player (runs in separate window)
            if (type === 'vox-pause') {
                if (typeof IrisVOX !== 'undefined') {
                    console.log('[PiP] Pausing VOX - pop-out video playing');
                    IrisVOX.pauseListening();
                }
                return;
            }
            if (type === 'vox-resume') {
                if (typeof IrisVOX !== 'undefined') {
                    console.log('[PiP] Resuming VOX - pop-out video idle');
                    IrisVOX.resumeListening();
                }
                return;
            }

            if (!this.isActive) return;

            if (type === 'queue-chunk') {
                // Route based on status
                if (data.status === 'completed') {
                    this.handleChunkReady(data);
                } else {
                    this.queueChunk(data);
                }
            }
        });
    }

    async launch() {
        if (this.isActive) {
            // Already active, just show
            this.show();
            return;
        }

        this.launchBtn.classList.add('loading');
        this.launchBtn.disabled = true;
        this.launchBtn.innerHTML = '⏳ Starting...';

        try {
            // Step 1: Enable TTS if not enabled
            if (!speechToggle.checked) {
                console.log('[PiP] Enabling TTS...');
                speechToggle.checked = true;
                speechToggle.dispatchEvent(new Event('change'));
            }

            // Step 2: Check for saved reference image
            const savedCheck = await fetch('/api/video/saved-image');
            const savedData = await savedCheck.json();

            if (!savedData.has_saved_image) {
                alert('No saved reference image found. Please set one up in the Admin console first.');
                throw new Error('No saved reference image');
            }

            // Step 3: Send video mode to server and wait for response
            // Server will create session and send mode_set with video_session_id
            // The mode_set handler will activate pipPlayer with the server's session
            console.log('[PiP] Requesting video mode from server...');
            this.statusElement.textContent = 'Starting session...';

            if (ws && ws.readyState === WebSocket.OPEN) {
                // Create a promise that resolves when mode_set is received
                const modeSetPromise = new Promise((resolve) => {
                    const timeout = setTimeout(() => {
                        console.log('[PiP] mode_set timeout after 10s');
                        resolve(false);
                    }, 10000);  // 10 second timeout for GPU swap

                    // Store resolver so mode_set handler can call it
                    this._modeSetResolver = (hasSession) => {
                        clearTimeout(timeout);
                        resolve(hasSession);
                    };
                });

                ws.send(JSON.stringify({
                    type: 'set_output_mode',
                    mode: 'video'
                }));
                console.log('[PiP] Sent video mode request to server, waiting for response...');

                // Wait for mode_set response
                const serverCreatedSession = await modeSetPromise;
                this._modeSetResolver = null;

                // If server-side routing created a session, we're done
                if (serverCreatedSession && this.isActive && this.sessionId) {
                    console.log('[PiP] ✓ Server-side routing activated, session:', this.sessionId);
                    this.launchBtn.classList.remove('loading');
                    this.launchBtn.disabled = false;
                    this.launchBtn.innerHTML = '🎬 Video';
                    return;
                }

                console.log('[PiP] Server did not create session, using local fallback');
            }

            // Fallback: Start local video session (if server-side routing is disabled)
            console.log('[PiP] Starting local video session...');
            const sessionResponse = await fetch('/api/video/start-session-saved', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    seed: 15,
                    a_cfg_scale: 2.0,
                    e_cfg_scale: 1.0,
                    r_cfg_scale: 1.0,
                    nfe: 10,
                    emotion: 'neutral',
                    no_crop: false
                })
            });

            if (!sessionResponse.ok) {
                const errorData = await sessionResponse.json();
                throw new Error(errorData.detail || 'Session start failed');
            }

            const { session_id } = await sessionResponse.json();
            this.sessionId = session_id;
            console.log('[PiP] Local session started:', session_id);

            // Notify TTSQueue about the session
            ttsQueue.videoChannel.postMessage({
                type: 'video-session-started',
                sessionId: session_id
            });

            // Mark player as open for TTSQueue routing
            ttsQueue.videoSessionId = session_id;
            ttsQueue.videoPlayerOpen = true;
            ttsQueue.chunkIndex = 0;

            // Show the PiP player
            this.isActive = true;
            this.show();
            this.startPolling();

            this.statusElement.textContent = 'Ready - Idle';
            this.launchBtn.innerHTML = '🎬 Video';

        } catch (error) {
            console.error('[PiP] Launch error:', error);
            this.statusElement.textContent = 'Error: ' + error.message;
            alert('Failed to start video: ' + error.message);
        } finally {
            this.launchBtn.classList.remove('loading');
            this.launchBtn.disabled = false;
            this.launchBtn.innerHTML = '🎬 Video';
        }
    }

    show() {
        this.container.classList.add('active');
        // Start idle video rotation (or play default loop if no videos)
        this.startIdleRotation();
    }

    close() {
        this.container.classList.remove('active');

        // Stop idle rotation
        this.stopIdleRotation();

        if (this.isActive) {
            // Clean up HLS if used
            if (this.useHLS) {
                this.cleanupHLS();
            }

            // End the session
            if (this.sessionId) {
                fetch(`/api/video/end-session/${this.sessionId}`, { method: 'POST' });
            }

            // Notify TTSQueue
            ttsQueue.videoChannel.postMessage({ type: 'video-session-ended' });
            ttsQueue.videoSessionId = null;
            ttsQueue.videoPlayerOpen = false;

            this.stopPolling();
            this.reset();
        }
    }

    popOut() {
        // Open the standalone video player
        const videoWindow = window.open(
            '/static/video_player.html',
            'iris-video',
            'width=800,height=700'
        );

        if (videoWindow && this.sessionId) {
            // Wait for pop-out to signal it's ready before sending session data
            // (pop-out needs to load HLS.js from CDN before its listener is active)
            const onPopOutReady = (event) => {
                if (event.data.type !== 'player-ready') return;
                ttsQueue.videoChannel.removeEventListener('message', onPopOutReady);

                console.log('[PiP] Pop-out ready, transferring session');
                const playlistUrl = this.hlsPlaylistUrl || `/api/video/hls/${this.sessionId}/playlist.m3u8`;
                if (this.useHLS) {
                    ttsQueue.videoChannel.postMessage({
                        type: 'start-session-hls',
                        data: {
                            sessionId: this.sessionId,
                            playlistUrl: playlistUrl
                        }
                    });
                } else {
                    ttsQueue.videoChannel.postMessage({
                        type: 'start-session',
                        data: { sessionId: this.sessionId }
                    });
                }
            };
            ttsQueue.videoChannel.addEventListener('message', onPopOutReady);

            // Hide PiP visually but keep generation active
            this.container.classList.remove('active');
            this.poppedOut = true;
            // Keep isActive = true so streamVideo/streamVideoHLS continues working
            this.stopIdleRotation();
            this.stopPolling();

            // Detach HLS.js from PiP video element (pop-out handles playback)
            if (this.hls) {
                this.hls.stopLoad();
                this.hls.detachMedia();
            }
            // Don't end session - it transfers to pop-out
        }
    }

    reset() {
        this.sessionId = null;
        this.videoQueue = [];
        this.currentChunkIndex = 0;
        this.isPlaying = false;
        this._playingTransition = false;  // Reset transition guard
        this._lastProcessedEndedChunk = -1;  // Reset ended event guard
        this._hlsPlaylistLoaded = false;  // Reset HLS playlist state
        this.stopIdleRotation();  // Stop rotation on reset
        this.currentThinkingVideo = null;  // Clear thinking video selection
        this.isActive = false;
        this.poppedOut = false;
        this.showLoop();
    }

    showLoop() {
        console.log('[PiP-Stream] showLoop() called - displaying idle loop');
        console.log('[PiP-Stream] DEBUG: serverSideRoutingEnabled =', ttsQueue.serverSideRoutingEnabled);
        console.log('[PiP-Stream] DEBUG: this.hls =', this.hls ? 'exists' : 'null');

        // Resume microphone when video playback ends
        if (typeof IrisVOX !== 'undefined') {
            console.log('[PiP] Resuming VOX - video playback ended');
            IrisVOX.resumeListening();
        }

        // Handle HLS cleanup based on routing mode
        if (this.hls) {
            if (ttsQueue.serverSideRoutingEnabled) {
                // Server-side routing: KEEP session alive for next turn
                // Just stop loading and detach, but don't delete server session
                console.log('[HLS] Server-side routing - pausing HLS (keeping session alive, NOT deleting)');
                this.hls.stopLoad();
                // Don't call cleanupHLS() - session persists for next turn
            } else {
                // Browser-side routing: full cleanup
                console.log('[HLS] Browser-side routing - calling cleanupHLS()');
                this.cleanupHLS();
            }
        }

        // CRITICAL: Pause BOTH video elements to prevent audio leakage
        this.videoElementA.pause();
        this.videoElementB.pause();
        this.videoElementA.classList.remove('active');
        this.videoElementB.classList.remove('active');
        // Clear sources to fully release resources (skip for server-side routing - HLS.js manages video)
        if (!ttsQueue.serverSideRoutingEnabled) {
            this.videoElementA.removeAttribute('src');
            this.videoElementB.removeAttribute('src');
        }

        // Hide thinking video
        this.thinkingElement.style.display = 'none';
        this.thinkingElement.pause();

        // Show idle loop with rotation (if active) or default loop
        this.loopElement.style.display = '';
        if (this.isActive) {
            // Start idle rotation
            this.startIdleRotation();
        } else {
            // Just play default loop (player not active)
            this.loopElement.src = '/static/loop.mp4';
            this.loopElement.loop = true;
            this.loopElement.play().catch(() => {});
        }
    }

    // Get the currently active and inactive video elements
    getPlayers() {
        if (this.activePlayer === 'A') {
            return { active: this.videoElementA, inactive: this.videoElementB };
        } else {
            return { active: this.videoElementB, inactive: this.videoElementA };
        }
    }

    // Swap which player is showing (for seamless transitions)
    swapPlayers() {
        const { active, inactive } = this.getPlayers();
        // IMPORTANT: Pause the old player before swapping
        active.pause();
        // Also mute the old player as extra protection against audio leakage
        active.muted = true;
        active.classList.remove('active');
        inactive.classList.add('active');
        // Ensure new active player is unmuted
        inactive.muted = false;
        this.activePlayer = this.activePlayer === 'A' ? 'B' : 'A';
        console.log('[PiP] Swapped to player', this.activePlayer);
    }

    // ============================================================
    // STREAMING VIDEO - Real-time video from FLOAT
    // ============================================================
    //
    // Each segment is a complete MP4 with audio.
    // Text requests are QUEUED and processed one at a time.
    // ============================================================

    async streamVideo(text) {
        /**
         * Queue text for streaming video generation.
         * Routes to HLS or legacy double-buffer based on useHLS flag.
         */
        // Filter out empty/whitespace-only text (e.g., just markdown like "**")
        const cleanedText = text.replace(/[\*\_\#\`\~\[\]\(\)\{\}\|\>\<]/g, '').trim();
        if (!cleanedText) {
            console.log('[PiP-Stream] Skipping empty text (only formatting):', text.substring(0, 30));
            return;
        }

        if (!this.sessionId) {
            console.log('[PiP-Stream] Cannot stream - no session');
            return;
        }

        // Route to HLS if enabled (works even when popped out - generation only)
        if (this.useHLS) {
            return this.streamVideoHLS(text);
        }

        // Legacy double-buffer approach requires active PiP
        if (!this.isActive) {
            console.log('[PiP-Stream] Cannot use legacy stream - PiP not active');
            return;
        }

        // Legacy double-buffer approach (fallback)
        if (!this.textQueue) {
            this.textQueue = [];
        }

        this.textQueue.push(text);
        console.log(`[PiP-Stream] Queued text (${this.textQueue.length} in queue):`, text.substring(0, 50) + '...');

        if (!this._processingTextQueue) {
            this.processTextQueue();
        }
    }

    // =================================================================
    // HLS Streaming Methods
    // =================================================================

    async initHLS() {
        /**
         * Initialize HLS.js for playback.
         */
        if (this.hlsInitialized) return;

        if (!Hls.isSupported()) {
            console.error('[HLS] HLS.js not supported in this browser');
            this.useHLS = false;
            return;
        }

        // CRITICAL: Remove legacy double-buffer event handlers
        // These conflict with HLS.js and cause playback issues
        if (this._legacyEndedHandler) {
            console.log('[HLS] Removing legacy ended handlers');
            this.videoElementA.removeEventListener('ended', this._legacyEndedHandler);
            this.videoElementB.removeEventListener('ended', this._legacyEndedHandler);
            this._legacyEndedHandler = null;
        }

        // Initialize HLS session on server
        try {
            const response = await fetch(`/api/video/hls/init/${this.sessionId}`, {
                method: 'POST'
            });
            if (!response.ok) {
                throw new Error('Failed to init HLS session');
            }
            const data = await response.json();
            this.hlsPlaylistUrl = data.playlist_url;
            console.log('[HLS] Server session initialized:', this.hlsPlaylistUrl);
        } catch (e) {
            console.error('[HLS] Failed to init server session:', e);
            this.useHLS = false;
            return;
        }

        // Create HLS.js instance for EVENT stream (segments added progressively)
        // KEY: We want VOD-like behavior (play from start, no seeking to live edge)
        this.hls = new Hls({
            debug: false,  // Disable debug noise now that freezing is fixed
            enableWorker: true,
            lowLatencyMode: false,

            // Buffer settings - be very tolerant of gaps/holes
            maxBufferLength: 60,
            maxMaxBufferLength: 120,
            backBufferLength: 30,
            maxBufferHole: 5.0,
            maxStarvationDelay: 20,
            highBufferWatchdogPeriod: 3,

            // Hole/discontinuity handling
            nudgeOffset: 0.5,
            nudgeMaxRetry: 10,
            maxFragLookUpTolerance: 1.0,

            // CRITICAL: Disable live sync - we want VOD behavior, not live edge seeking
            // Set very high values so HLS.js never tries to seek to "live edge"
            // Note: liveMaxLatencyDurationCount MUST be > liveSyncDurationCount
            liveSyncDurationCount: 9999,         // Never sync to live edge
            liveMaxLatencyDurationCount: 99999,  // Allow infinite latency (must be > liveSyncDurationCount)
            liveDurationInfinity: false,

            // Start from beginning, not live edge
            startPosition: 0,

            // Loading timeouts
            manifestLoadingTimeOut: 30000,
            manifestLoadingMaxRetry: 6,
            levelLoadingTimeOut: 10000,
            levelLoadingMaxRetry: 6,
            fragLoadingTimeOut: 60000,

            // Start position - from beginning
            startPosition: 0,
            startLevel: -1,
        });

        // Use the primary video element
        this.hls.attachMedia(this.videoElementA);

        this.hls.on(Hls.Events.MANIFEST_PARSED, () => {
            console.log('[HLS] Manifest parsed, starting playback');
            this.videoElementA.play().catch(e => console.log('[HLS] Autoplay blocked:', e));
        });

        this.hls.on(Hls.Events.ERROR, (event, data) => {
            if (data.fatal) {
                console.error('[HLS] Fatal error:', data.type, data.details);
                switch (data.type) {
                    case Hls.ErrorTypes.NETWORK_ERROR:
                        console.log('[HLS] Network error, trying to recover...');
                        this.hls.startLoad();
                        break;
                    case Hls.ErrorTypes.MEDIA_ERROR:
                        console.log('[HLS] Media error, trying to recover...');
                        this.hls.recoverMediaError();
                        break;
                    default:
                        console.error('[HLS] Unrecoverable error');
                        this.hls.destroy();
                        break;
                }
            } else {
                console.warn('[HLS] Non-fatal error:', data.type, data.details);

                // Handle specific non-fatal errors
                if (data.details === 'bufferStalledError') {
                    console.log('[HLS] Buffer stalled, attempting recovery...');
                    // Try to recover by restarting load from current position
                    this.hls.startLoad();
                } else if (data.details === 'bufferNudgeOnStall') {
                    console.log('[HLS] Buffer nudge on stall');
                    // This is normal recovery behavior, just log it
                }
            }
        });

        this.hls.on(Hls.Events.FRAG_LOADED, (event, data) => {
            console.log(`[HLS] Fragment loaded: sn=${data.frag.sn}, duration=${data.frag.duration?.toFixed(1)}s`);
        });

        this.hls.on(Hls.Events.LEVEL_LOADED, (event, data) => {
            console.log(`[HLS] Playlist loaded: ${data.details.fragments?.length || 0} segments, endList=${data.details.endList}`);
        });

        this.hls.on(Hls.Events.BUFFER_APPENDED, (event, data) => {
            // Hide loops and show video when we have content
            if (this.loopElement.style.display !== 'none' || this.thinkingElement.style.display !== 'none') {
                this.stopIdleRotation();  // Stop rotation when streaming
                this.loopElement.style.display = 'none';
                this.hideThinking();
                this.videoElementA.style.display = 'block';
                this.videoElementA.classList.add('active');

                // Mute microphone while video plays to prevent Iris hearing herself
                if (typeof IrisVOX !== 'undefined') {
                    console.log('[PiP] Pausing VOX - video playback starting');
                    IrisVOX.pauseListening();
                }
            }
            // Log buffer state
            const buffered = this.videoElementA.buffered;
            if (buffered.length > 0) {
                const bufferEnd = buffered.end(buffered.length - 1);
                const currentTime = this.videoElementA.currentTime;
                console.log(`[HLS] Buffer: ${(bufferEnd - currentTime).toFixed(1)}s ahead (pos=${currentTime.toFixed(1)}s, end=${bufferEnd.toFixed(1)}s)`);
            }
        });

        this.hls.on(Hls.Events.BUFFER_EOS, () => {
            console.log('[HLS] Buffer end of stream - all content buffered');
        });

        // Handle video ended - show loop again
        // Store the handler so we can remove it during cleanup
        this._hlsEndedHandler = () => {
            if (this.useHLS && this.hlsInitialized) {
                console.log('[HLS] Playback complete');
                this.showLoop();
                this.statusElement.textContent = 'Ready';
            }
        };
        this.videoElementA.addEventListener('ended', this._hlsEndedHandler);

        this.hlsInitialized = true;
        console.log('[HLS] Initialized');
    }

    initHLSPlayback(playlistUrl) {
        /**
         * Initialize HLS.js for server-side routing playback.
         * Server already handles HLS session setup - we just attach to the playlist.
         */
        console.log('[HLS-Server] initHLSPlayback called, hlsInitialized =', this.hlsInitialized, 'hls =', this.hls ? 'exists' : 'null');

        if (this.hlsInitialized) {
            console.log('[HLS-Server] Already initialized, returning early');
            return;
        }

        if (!Hls.isSupported()) {
            console.error('[HLS-Server] HLS.js not supported in this browser');
            this.useHLS = false;
            return;
        }

        // Remove legacy event handlers that conflict with HLS.js
        if (this._legacyEndedHandler) {
            console.log('[HLS-Server] Removing legacy ended handlers');
            this.videoElementA.removeEventListener('ended', this._legacyEndedHandler);
            this.videoElementB.removeEventListener('ended', this._legacyEndedHandler);
            this._legacyEndedHandler = null;
        }

        this.hlsPlaylistUrl = playlistUrl;
        console.log('[HLS-Server] Using server playlist:', playlistUrl);

        // Create HLS.js instance configured for EVENT stream
        this.hls = new Hls({
            debug: false,  // Disable debug - timestamps now fixed via FFmpeg remux
            enableWorker: true,
            lowLatencyMode: false,

            // Buffer settings - tolerate gaps during generation
            maxBufferLength: 60,
            maxMaxBufferLength: 120,
            backBufferLength: 30,
            maxBufferHole: 0.5,  // Smaller hole tolerance now that timestamps are correct
            maxStarvationDelay: 10,
            highBufferWatchdogPeriod: 3,

            // Hole/discontinuity handling
            nudgeOffset: 0.1,
            nudgeMaxRetry: 5,
            maxFragLookUpTolerance: 0.25,  // Tighter tolerance with proper timestamps

            // VOD behavior - don't seek to live edge
            liveSyncDurationCount: 9999,
            liveMaxLatencyDurationCount: 99999,
            liveDurationInfinity: false,

            // Start from beginning
            startPosition: 0,
            startLevel: -1,

            // Loading timeouts
            manifestLoadingTimeOut: 30000,
            manifestLoadingMaxRetry: 6,
            levelLoadingTimeOut: 10000,
            levelLoadingMaxRetry: 6,
            fragLoadingTimeOut: 60000,
        });

        // Attach to video element
        this.hls.attachMedia(this.videoElementA);

        this.hls.on(Hls.Events.MANIFEST_PARSED, () => {
            console.log('[HLS-Server] Manifest parsed, starting playback');
            this.videoElementA.play().catch(e => console.log('[HLS-Server] Autoplay blocked:', e));
        });

        this.hls.on(Hls.Events.ERROR, (event, data) => {
            if (data.fatal) {
                console.error('[HLS-Server] Fatal error:', data.type, data.details);
                switch (data.type) {
                    case Hls.ErrorTypes.NETWORK_ERROR:
                        console.log('[HLS-Server] Network error, trying to recover...');
                        this.hls.startLoad();
                        break;
                    case Hls.ErrorTypes.MEDIA_ERROR:
                        console.log('[HLS-Server] Media error, trying to recover...');
                        this.hls.recoverMediaError();
                        break;
                    default:
                        console.error('[HLS-Server] Unrecoverable error');
                        break;
                }
            } else if (data.details === 'manifestLoadError' || data.details === 'manifestParsingError') {
                // Playlist not ready yet - retry after delay
                console.log('[HLS-Server] Playlist not ready, will retry...');
            }
        });

        this.hls.on(Hls.Events.FRAG_LOADED, (event, data) => {
            console.log(`[HLS-Server] Fragment loaded: sn=${data.frag.sn}, duration=${data.frag.duration?.toFixed(1)}s, start=${data.frag.start?.toFixed(2)}s`);
        });

        this.hls.on(Hls.Events.FRAG_CHANGED, (event, data) => {
            console.log(`[HLS-Server] Fragment changed: sn=${data.frag.sn}, playing from ${data.frag.start?.toFixed(2)}s`);
        });

        this.hls.on(Hls.Events.LEVEL_LOADED, (event, data) => {
            const details = data.details;
            console.log(`[HLS-Server] Playlist loaded: ${details.fragments?.length || 0} segments, live=${details.live}, type=${details.type}`);
            console.log(`[HLS-Server] Video currentTime: ${this.videoElementA.currentTime?.toFixed(2)}s`);
        });

        // Track seeking events (for debugging, no longer blocking)
        this.videoElementA.addEventListener('seeking', () => {
            console.log(`[HLS-Server] VIDEO SEEKING to ${this.videoElementA.currentTime?.toFixed(2)}s`);
        });

        this.videoElementA.addEventListener('seeked', () => {
            console.log(`[HLS-Server] VIDEO SEEKED to ${this.videoElementA.currentTime?.toFixed(2)}s`);
        });

        // Track when video actually plays
        this.videoElementA.addEventListener('playing', () => {
            console.log(`[HLS-Server] VIDEO PLAYING at ${this.videoElementA.currentTime?.toFixed(2)}s`);
        });

        this.videoElementA.addEventListener('waiting', () => {
            console.log(`[HLS-Server] VIDEO WAITING (buffering) at ${this.videoElementA.currentTime?.toFixed(2)}s`);
        });

        this.hls.on(Hls.Events.BUFFER_APPENDED, (event, data) => {
            // Hide loops and show video when we have content
            if (this.loopElement.style.display !== 'none' || this.thinkingElement.style.display !== 'none') {
                this.stopIdleRotation();
                this.loopElement.style.display = 'none';
                this.hideThinking();
                this.videoElementA.style.display = 'block';
                this.videoElementA.classList.add('active');

                // Mute microphone while video plays to prevent Iris hearing herself
                if (typeof IrisVOX !== 'undefined') {
                    console.log('[PiP] Pausing VOX - video playback starting (server-side)');
                    IrisVOX.pauseListening();
                }
            }
        });

        this.hls.on(Hls.Events.BUFFER_EOS, () => {
            console.log('[HLS-Server] End of stream');
        });

        // Handle playback complete
        this._hlsEndedHandler = () => {
            if (this.useHLS && this.hlsInitialized) {
                console.log('[HLS-Server] Playback complete');
                this.showLoop();
                this.statusElement.textContent = 'Ready';
            }
        };
        this.videoElementA.addEventListener('ended', this._hlsEndedHandler);

        this.hlsInitialized = true;
        console.log('[HLS-Server] Initialized, waiting for segments...');

        // Note: We don't load the source yet - wait for first segment notification
        // The onHLSSegmentReady handler will trigger the playlist load
    }

    // Called when WebSocket receives hls_segment_ready
    onHLSSegmentReady(data) {
        console.log('[HLS] onHLSSegmentReady called, hlsInitialized =', this.hlsInitialized, 'hls =', this.hls ? 'exists' : 'null');
        if (!this.hlsInitialized || !this.hls) {
            console.log('[HLS] onHLSSegmentReady returning early - not initialized');
            return;
        }

        console.log(`[HLS] WebSocket: segment ${data.segment} ready (idx ${data.segment_index}, ${data.duration?.toFixed(2)}s)`);

        // Use playlist URL from data if provided, otherwise use stored URL
        const playlistUrl = data.playlist_url || this.hlsPlaylistUrl;

        // Wait for 3rd segment (index 2) before starting playback for buffer
        if (data.segment_index === 2 && playlistUrl && !this._hlsPlaylistLoaded) {
            console.log('[HLS] Third segment ready, loading playlist with buffer:', playlistUrl);
            console.log('[HLS] loadSource() called - this should only happen ONCE per response');
            this._hlsPlaylistLoaded = true;
            this.hls.loadSource(playlistUrl);

            // Show thinking while buffering first segment
            this.showThinking();
            this.statusElement.textContent = 'Loading video...';
        }

        // Update status
        if (data.segment_index > 0) {
            this.statusElement.textContent = `Streaming (${data.segment_index + 1} segments)`;
        }
    }

    // Called when WebSocket receives hls_new_turn (server reset HLS for new response)
    onHLSNewTurn(data) {
        console.log('[HLS] New turn - resetting for fresh playlist');
        this._hlsPlaylistLoaded = false;

        // Destroy and recreate HLS.js to fully reset state
        if (this.hls) {
            this.hls.destroy();
            this.hls = null;
        }
        // CRITICAL: Reset hlsInitialized so initHLSPlayback will create new instance
        this.hlsInitialized = false;

        // Reset video element
        this.videoElementA.pause();
        this.videoElementA.currentTime = 0;

        // Reinitialize HLS.js fresh
        this.initHLSPlayback(data.playlist_url);

        // Show thinking while waiting for first segment
        this.showThinking();
        this.statusElement.textContent = 'Preparing video...';

        console.log('[HLS] onHLSNewTurn - HLS destroyed and reinitialized for new turn');
    }

    // Called when WebSocket receives hls_stream_complete
    onHLSStreamComplete(data) {
        console.log('[HLS] Stream complete notification received');
        this.statusElement.textContent = 'Playback finishing...';

        // The HLS.js BUFFER_EOS and video 'ended' events will handle the rest
        // Just reset the playlist loaded flag for next stream
        this._hlsPlaylistLoaded = false;
    }

    async streamVideoHLS(text) {
        /**
         * Queue text for HLS video generation.
         * Text is sent to server which generates segments and updates playlist.
         * HLS.js handles playback automatically.
         */
        console.log(`[HLS] Queuing text: "${text.substring(0, 50)}..."`);

        // Initialize HLS if needed
        if (!this.hlsInitialized) {
            await this.initHLS();
            if (!this.useHLS) {
                // Fallback to legacy if HLS init failed
                return this.streamVideoLegacy(text);
            }
        }

        // Queue the text
        this.hlsTextQueue.push(text);
        this.statusElement.textContent = `Queued (${this.hlsTextQueue.length})`;

        // Start processing if not already
        if (!this._hlsProcessing) {
            this.processHLSQueue();
        }
    }

    async processHLSQueue() {
        /**
         * Process HLS text queue - sends text to server for generation.
         * Server adds segments to playlist, HLS.js picks them up automatically.
         *
         * Key: Don't load playlist until first segment is ready.
         */
        if (this._hlsProcessing) return;
        this._hlsProcessing = true;

        let firstSegmentReady = this.hls.url ? true : false;
        let totalSegmentsGenerated = 0;

        while (this.hlsTextQueue.length > 0) {
            const text = this.hlsTextQueue.shift();
            console.log(`[HLS] Generating: "${text.substring(0, 50)}..." (${this.hlsTextQueue.length} remaining)`);
            this.statusElement.textContent = `Generating... (${this.hlsTextQueue.length} queued)`;

            try {
                const response = await fetch('/api/video/hls/stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: new URLSearchParams({
                        session_id: this.sessionId,
                        text: text,
                        quality: this.videoQuality
                    })
                });

                if (!response.ok) {
                    const error = await response.text();
                    console.error('[HLS] Generation error:', error);
                    continue;
                }

                const result = await response.json();
                totalSegmentsGenerated += result.segments_added;
                console.log(`[HLS] Generated ${result.segments_added} segments, total: ${result.total_segments}`);

                // Load playlist after first text generates segments
                // Skip playback setup when popped out (pop-out handles its own HLS.js)
                if (!this.poppedOut && !firstSegmentReady && result.segments_added > 0) {
                    console.log('[HLS] First segments ready, loading playlist:', this.hlsPlaylistUrl);
                    this.hls.loadSource(this.hlsPlaylistUrl);
                    firstSegmentReady = true;

                    // Hide loops, show video
                    this.stopIdleRotation();
                    this.loopElement.style.display = 'none';
                    this.hideThinking();
                    this.videoElementA.style.display = 'block';
                    this.videoElementA.classList.add('active');
                }

            } catch (e) {
                console.error('[HLS] Generation failed:', e);
            }
        }

        this._hlsProcessing = false;

        if (totalSegmentsGenerated > 0) {
            this.statusElement.textContent = 'Playing...';
            console.log(`[HLS] Queue complete, ${totalSegmentsGenerated} total segments`);
        } else {
            this.statusElement.textContent = 'Ready';
            console.log('[HLS] Queue complete, no segments generated');
        }

        // If stream has ended (no more text coming), finalize the playlist
        if (this._hlsStreamEnded && this.hlsTextQueue.length === 0) {
            console.log('[HLS] Stream ended, finalizing playlist');
            await this.completeHLS();
        }
    }

    /**
     * Signal that no more text will be queued for this HLS session.
     * Called when the LLM response is complete.
     */
    finalizeHLSStream() {
        if (!this.useHLS || !this.hlsInitialized) return;

        console.log('[HLS] finalizeHLSStream called - marking stream as ended');
        this._hlsStreamEnded = true;

        // If queue is already empty and not processing, complete now
        if (this.hlsTextQueue.length === 0 && !this._hlsProcessing) {
            this.completeHLS();
        }
        // Otherwise, processHLSQueue will call completeHLS when done
    }

    async completeHLS() {
        /**
         * Signal that no more segments will be added.
         * Adds EXT-X-ENDLIST to playlist.
         */
        if (!this.hlsInitialized) return;

        try {
            await fetch(`/api/video/hls/complete/${this.sessionId}`, {
                method: 'POST'
            });
            console.log('[HLS] Playlist marked complete');
        } catch (e) {
            console.error('[HLS] Failed to complete playlist:', e);
        }
    }

    cleanupHLS() {
        /**
         * Clean up HLS resources.
         */
        console.log('[HLS] cleanupHLS() called - STACK TRACE:');
        console.trace();

        // Remove the ended event listener to prevent accumulation
        if (this._hlsEndedHandler) {
            this.videoElementA.removeEventListener('ended', this._hlsEndedHandler);
            this._hlsEndedHandler = null;
        }

        if (this.hls) {
            this.hls.destroy();
            this.hls = null;
        }
        this.hlsInitialized = false;
        this.hlsTextQueue = [];
        this._hlsProcessing = false;
        this._hlsStreamEnded = false;

        // Clean up server-side
        if (this.sessionId) {
            fetch(`/api/video/hls/${this.sessionId}`, {
                method: 'DELETE'
            }).catch(() => {});
        }

        console.log('[HLS] Cleanup complete');
    }

    // Legacy method for fallback
    streamVideoLegacy(text) {
        if (!this.textQueue) {
            this.textQueue = [];
        }
        this.textQueue.push(text);
        if (!this._processingTextQueue) {
            this.processTextQueue();
        }
    }

    async processTextQueue() {
        /**
         * Process queued text items - pipeline generation ahead of playback.
         * Starts generating next text as soon as current fetch completes,
         * not waiting for playback to finish.
         */
        if (this._processingTextQueue) return;
        if (!this.textQueue || this.textQueue.length === 0) return;

        this._processingTextQueue = true;

        while (this.textQueue.length > 0) {
            const text = this.textQueue.shift();
            console.log(`[PiP-Stream] Processing text (${this.textQueue.length} remaining):`, text.substring(0, 50) + '...');

            // Start generation - returns when FETCH completes, not when PLAYBACK completes
            await this.generateSegments(text);
        }

        this._processingTextQueue = false;
        console.log('[PiP-Stream] All text generated, waiting for playback to finish');
    }

    async generateSegments(text) {
        /**
         * Generate video segments for text. Returns when FETCH completes,
         * allowing the next text to start generating while this one plays.
         * Segments are added to the shared queue for continuous playback.
         */
        // Initialize queue only if this is the first text
        if (!this.streamQueue || this.streamQueue.length === 0) {
            this.streamQueue = [];
            this.streamIndex = 0;
            this._prebufferCount = 2;
            this._prebuffering = true;
        }

        // Track active generations so we know when ALL are done
        this._activeGenerations = (this._activeGenerations || 0) + 1;
        this.streamingMode = true;
        this.statusElement.textContent = 'Generating...';

        // Track text generation count for debugging
        this._textGenCount = (this._textGenCount || 0) + 1;
        const textGenId = this._textGenCount;

        this.abortController = new AbortController();

        try {
            console.log(`[PiP-Stream] 📝 Starting generation #${textGenId} for: "${text.substring(0, 50)}..." [quality=${this.videoQuality}]`);

            const response = await fetch('/api/video/stream-ndjson', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({
                    session_id: this.sessionId,
                    text: text,
                    quality: this.videoQuality
                }),
                signal: this.abortController.signal
            });

            if (!response.ok) {
                throw new Error(`Stream failed: ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            // Helper to process a single NDJSON line
            const processLine = (line) => {
                if (!line.trim()) return;

                try {
                    const data = JSON.parse(line);

                    // Log server's chunk_idx for debugging
                    if (data.chunk_idx !== undefined) {
                        console.log(`[PiP-Stream] 🔗 Server sent chunk_idx=${data.chunk_idx}, total_chunks=${data.total_chunks}, is_last=${data.is_last}`);
                    }

                    if (data.error) {
                        console.error('[PiP-Stream] Error:', data.error);
                        return;
                    }

                    if (data.segment) {
                        // Decode base64 to blob
                        const binaryString = atob(data.segment);
                        const bytes = new Uint8Array(binaryString.length);
                        for (let i = 0; i < binaryString.length; i++) {
                            bytes[i] = binaryString.charCodeAt(i);
                        }
                        const blob = new Blob([bytes], { type: 'video/mp4' });
                        const url = URL.createObjectURL(blob);

                        // Add to shared queue
                        const queueIndex = this.streamQueue.length;
                        this.streamQueue.push({
                            url: url,
                            index: queueIndex,
                            isLast: data.is_last || false,
                            frames: data.frames || 0,
                            duration: data.duration || 0,
                            serverChunkIdx: data.chunk_idx,  // Track server's index for debugging
                            textGenId: textGenId,            // Which text generation this belongs to
                            serverTotal: data.total_chunks   // Total chunks for this text
                        });

                        const sizeKB = data.size_kb || Math.round(blob.size / 1024);
                        const bufferedCount = this.streamQueue.length - this.streamIndex;
                        console.log(`[PiP-Stream] 📥 Received segment #${queueIndex + 1} [text#${textGenId} chunk${data.chunk_idx}/${data.total_chunks}]: ${data.duration?.toFixed(1) || '?'}s, ${sizeKB}KB (${bufferedCount} ahead) [${data.quality || 'unknown'}]`);

                        if (this._prebuffering) {
                            this.statusElement.textContent = `Buffering ${bufferedCount}/${this._prebufferCount}`;

                            if (bufferedCount >= this._prebufferCount) {
                                console.log(`[PiP-Stream] Pre-buffer complete (${bufferedCount} segments), starting playback`);
                                this._prebuffering = false;
                                if (!this.isPlaying) {
                                    this.playStreamQueue();
                                }
                            }
                        } else {
                            this.statusElement.textContent = `+${sizeKB}KB (${bufferedCount} buffered)`;
                            if (!this.isPlaying) {
                                this.playStreamQueue();
                            }
                        }
                    } else {
                        // Received line without segment data
                        console.warn(`[PiP-Stream] ⚠️ Received data without segment: chunk_idx=${data.chunk_idx}`);
                    }
                } catch (e) {
                    console.error('[PiP-Stream] Parse error:', e, 'Line:', line.substring(0, 100));
                }
            };

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    processLine(line);
                }
            }

            // Process any remaining content in buffer after stream ends
            if (buffer.trim()) {
                console.log('[PiP-Stream] Processing remaining buffer content');
                processLine(buffer);
            }

            // This text's fetch is complete - return so next text can start generating
            this._activeGenerations--;
            console.log(`[PiP-Stream] Generation complete for text (${this._activeGenerations} still generating, ${this.textQueue?.length || 0} queued)`);

            // If no more generations pending and no more in queue, mark streaming done
            if (this._activeGenerations === 0 && (!this.textQueue || this.textQueue.length === 0)) {
                this.streamingMode = false;
                console.log('[PiP-Stream] All generations complete');
            }

        } catch (error) {
            this._activeGenerations--;
            if (error.name === 'AbortError') {
                console.log('[PiP-Stream] Generation aborted');
            } else {
                console.error('[PiP-Stream] Generation error:', error);
            }
            if (this._activeGenerations === 0) {
                this.streamingMode = false;
            }
        }
    }

    async playStreamQueue() {
        /**
         * Play segments using double-buffer for seamless transitions.
         * Preloads next segment while current plays.
         */
        if (this.isPlaying) return;

        const segment = this.streamQueue[this.streamIndex];
        if (!segment) {
            // No segment ready yet - check if more coming
            const moreGenerating = this._activeGenerations > 0;
            const moreQueued = this.textQueue && this.textQueue.length > 0;
            const stillStreaming = this.streamingMode || this._prebuffering || moreGenerating || moreQueued;

            console.log(`[PiP-Stream] No segment at index ${this.streamIndex}. Queue has ${this.streamQueue.length} total. ` +
                `streaming=${this.streamingMode}, prebuffer=${this._prebuffering}, generating=${moreGenerating}, queued=${moreQueued}`);

            if (stillStreaming) {
                const buffered = this.streamQueue.length - this.streamIndex;
                this.statusElement.textContent = `Waiting for segments... (${buffered} buffered)`;
                // Will be called again when segment arrives
            } else {
                // All done - no more segments and nothing generating
                console.log(`[PiP-Stream] ✓ All done - streamIndex=${this.streamIndex}, queueLen=${this.streamQueue.length}, ` +
                    `streamingMode=${this.streamingMode}, activeGens=${this._activeGenerations}, textQueue=${this.textQueue?.length || 0}`);
                this.finishStreamPlayback();
            }
            return;
        }

        // Validate segment URL
        if (!segment.url) {
            console.error(`[PiP-Stream] Segment ${this.streamIndex + 1} has no URL - SKIPPING (this shouldn't happen)`);
            this.streamIndex++;
            this.playStreamQueue();
            return;
        }

        this.isPlaying = true;
        const { active, inactive } = this.getPlayers();
        const playingSegmentIndex = this.streamIndex;  // Capture for closure

        // CRITICAL: Clear ALL event handlers on BOTH players to prevent stale handlers
        active.onended = null;
        active.onerror = null;
        active.oncanplay = null;
        active.onloadeddata = null;
        inactive.onended = null;
        inactive.onerror = null;
        inactive.oncanplay = null;
        inactive.onloadeddata = null;

        // Hide loop, show video
        this.stopIdleRotation();
        this.loopElement.style.display = 'none';
        this.hideThinking();
        active.classList.add('active');
        active.muted = false;

        // Mute microphone while video plays to prevent Iris hearing herself
        if (typeof IrisVOX !== 'undefined' && !this._voxPausedForStream) {
            console.log('[PiP] Pausing VOX - stream video playback starting');
            IrisVOX.pauseListening();
            this._voxPausedForStream = true;
        }

        const bufferedAhead = this.streamQueue.length - this.streamIndex - 1;
        const segDuration = segment.duration || (segment.frames ? segment.frames / 25 : '?');
        const textInfo = segment.textGenId !== undefined ? `[text#${segment.textGenId} chunk${segment.serverChunkIdx}/${segment.serverTotal}]` : '';
        console.log(`[PiP-Stream] ▶ Playing segment #${this.streamIndex + 1}/${this.streamQueue.length} ${textInfo} (${bufferedAhead} ahead, ${typeof segDuration === 'number' ? segDuration.toFixed(1) : segDuration}s)`);
        this.statusElement.textContent = `Playing ${this.streamIndex + 1} (${bufferedAhead} buffered)`;

        try {
            // Load current segment if not already loaded
            if (active.src !== segment.url && !active.src.includes(segment.url)) {
                active.src = segment.url;
                await new Promise((resolve, reject) => {
                    const onReady = () => {
                        active.oncanplay = null;
                        active.onloadeddata = null;
                        resolve();
                    };
                    active.oncanplay = onReady;
                    active.onloadeddata = onReady;
                    active.onerror = reject;
                    // Check if already ready
                    if (active.readyState >= 3) {
                        active.oncanplay = null;
                        active.onloadeddata = null;
                        resolve();
                    }
                });
            }

            // Start playback
            await active.play();

            // PRELOAD next segment into inactive player while this one plays
            // But skip preloading if current segment is short - won't have time
            const currentDuration = segment.frames ? segment.frames / 25 : 10;
            const nextSegment = this.streamQueue[this.streamIndex + 1];

            if (currentDuration >= 2.0 && nextSegment && nextSegment.url) {
                console.log(`[PiP-Stream] Preloading segment ${this.streamIndex + 2}`);
                // Clear inactive handlers AGAIN before preloading to be safe
                inactive.onended = null;
                inactive.onerror = null;
                inactive.muted = true;
                inactive.src = nextSegment.url;
                inactive.load();
            } else if (currentDuration < 2.0) {
                console.log(`[PiP-Stream] Skipping preload - current segment too short (${currentDuration.toFixed(1)}s)`);
                inactive.removeAttribute('src');
            } else {
                inactive.removeAttribute('src');
            }

            // Wait for video to end - use guard to prevent double-fire
            let hasEnded = false;
            await new Promise((resolve) => {
                active.onended = () => {
                    if (hasEnded) {
                        console.warn(`[PiP-Stream] ⚠️ DUPLICATE ended event for segment ${playingSegmentIndex + 1} - ignoring`);
                        return;
                    }
                    hasEnded = true;
                    active.onended = null;  // Clear immediately
                    console.log(`[PiP-Stream] Segment ${playingSegmentIndex + 1} ended normally (duration: ${active.duration?.toFixed(1)}s)`);
                    resolve();
                };
                active.onerror = (e) => {
                    if (hasEnded) return;
                    hasEnded = true;
                    active.onerror = null;
                    console.error(`[PiP-Stream] Segment ${playingSegmentIndex + 1} ERROR:`, e);
                    resolve();
                };
            });

            // Move to next
            this.streamIndex++;
            this.isPlaying = false;

            // Clean up the segment that just finished
            // But DON'T revoke if it's still preloaded in the other player
            const segmentUrl = segment.url;
            if (inactive.src !== segmentUrl) {
                URL.revokeObjectURL(segmentUrl);
            }
            segment.url = null;  // Mark as used

            // If next segment was preloaded into inactive player, swap for instant playback
            const nextSeg = this.streamQueue[this.streamIndex];
            if (nextSeg && nextSeg.url && inactive.src && inactive.src === nextSeg.url) {
                console.log('[PiP-Stream] Swapping to preloaded player');
                this.swapPlayers();
            }

            // Play next segment
            this.playStreamQueue();

        } catch (error) {
            console.error('[PiP-Stream] Playback error:', error);
            this.isPlaying = false;
            this.streamIndex++;
            this.playStreamQueue();
        }
    }

    finishStreamPlayback() {
        /**
         * Clean up after ALL playback completes.
         * Only called when queue is empty AND no more generations pending.
         */
        // Skip legacy cleanup when HLS is active
        if (this.useHLS && this.hlsInitialized) {
            console.log('[PiP-Stream] finishStreamPlayback skipped - HLS is active');
            return;
        }
        // Diagnostic: show what was played vs what was in queue
        const totalInQueue = this.streamQueue ? this.streamQueue.length : 0;
        const playedCount = this.streamIndex;
        const skippedCount = totalInQueue - playedCount;
        console.log(`[PiP-Stream] ✓✓ finishStreamPlayback called - played ${playedCount}/${totalInQueue} segments` +
            (skippedCount > 0 ? ` ⚠️ ${skippedCount} SKIPPED!` : ''));

        // If segments were skipped, log details
        if (skippedCount > 0 && this.streamQueue) {
            console.error('[PiP-Stream] SKIPPED SEGMENTS:');
            for (let i = playedCount; i < totalInQueue; i++) {
                const seg = this.streamQueue[i];
                console.error(`  - Segment ${i + 1}: text#${seg.textGenId} chunk${seg.serverChunkIdx}/${seg.serverTotal}, ${seg.duration?.toFixed(1)}s, url=${seg.url ? 'present' : 'MISSING'}`);
            }
        }

        try {
            // Clean up any remaining URLs
            this.streamQueue.forEach(seg => {
                if (seg.url) {
                    try { URL.revokeObjectURL(seg.url); } catch(e) {}
                    seg.url = null;
                }
            });

            // Clear video player sources
            this.videoElementA.removeAttribute('src');
            this.videoElementB.removeAttribute('src');

            this.streamQueue = [];
            this.streamIndex = 0;
            this.isPlaying = false;
            this._prebuffering = false;
            this._activeGenerations = 0;
            this._processingTextQueue = false;
            this._voxPausedForStream = false;

            this.showLoop();
            this.statusElement.textContent = 'Ready';
            console.log('[PiP-Stream] ✓✓ Cleanup complete, loop should be visible');
        } catch (e) {
            console.error('[PiP-Stream] Error in finishStreamPlayback:', e);
        }
    }

    // ============================================================
    // Legacy chunk-based methods (for non-streaming fallback)
    // ALL METHODS BELOW ARE SKIPPED WHEN HLS IS ACTIVE
    // ============================================================

    queueChunk(chunkData) {
        // Skip legacy queueing when HLS is active
        if (this.useHLS && this.hlsInitialized) {
            return;
        }

        const exists = this.videoQueue.some(c => c.chunk_index === chunkData.chunk_index);
        if (!exists) {
            this.videoQueue.push(chunkData);
            this.videoQueue.sort((a, b) => a.chunk_index - b.chunk_index);
            console.log('[PiP] Chunk queued:', chunkData.chunk_index);
            this.updateQueueInfo();

            // Only start playback if not already playing AND not in a transition
            if (!this.isPlaying && !this._playingTransition) {
                this.playNextChunk();
            }
        }
    }

    handleChunkReady(data) {
        // Skip legacy handling when HLS is active
        if (this.useHLS && this.hlsInitialized) {
            return;  // HLS uses onHLSSegmentReady() instead
        }

        // Handle WebSocket push for chunk status (replaces polling)
        const chunkIndex = data.chunk_index;
        const chunk = this.videoQueue.find(c => c.chunk_index === chunkIndex);

        if (!chunk) {
            console.log('[PiP] Received status for unknown chunk:', chunkIndex);
            return;
        }

        if (data.status === 'completed' && chunk.status !== 'completed') {
            chunk.status = 'completed';
            chunk.video_path = data.video_path;
            console.log('[PiP] Chunk ready (via WebSocket):', chunkIndex);

            // Play immediately if this is the chunk we're waiting for
            // Also check _playingTransition to prevent race conditions
            if (chunkIndex === this.currentChunkIndex && !this.isPlaying && !this._playingTransition) {
                this.playNextChunk();
            } else if (chunkIndex === this.currentChunkIndex + 1 && (this.isPlaying || this._playingTransition)) {
                // Next chunk is ready - preload it for seamless transition
                this.preloadNextChunk();
            }
        } else if (data.status === 'failed') {
            chunk.status = 'failed';
            chunk.error = data.error;
            console.log('[PiP] Chunk failed (via WebSocket):', chunkIndex, data.error);
        }

        this.updateQueueInfo();
    }

    startPolling() {
        // WebSocket push is now primary - polling disabled for bandwidth savings
        console.log('[PiP] Polling disabled - using WebSocket push for chunk status');
        // Legacy polling code removed - server now pushes video_chunk_ready messages
    }

    stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
    }

    async checkQueueStatus() {
        if (!this.sessionId) return;

        for (const chunk of this.videoQueue) {
            if (chunk.status === 'completed') continue;

            try {
                const response = await fetch(`/api/video/chunk-status/${this.sessionId}/${chunk.chunk_index}`);
                if (response.ok) {
                    const status = await response.json();

                    if (status.status === 'completed' && chunk.status !== 'completed') {
                        chunk.status = 'completed';
                        chunk.video_path = status.video_path;
                        console.log('[PiP] Chunk ready:', chunk.chunk_index);

                        if (chunk.chunk_index === this.currentChunkIndex && !this.isPlaying && !this._playingTransition) {
                            this.playNextChunk();
                        }
                    }
                }
            } catch (error) {
                console.error('[PiP] Error checking chunk status:', error);
            }
        }

        this.updateQueueInfo();
    }

    // Helper: Wait for video to be ready with timeout
    async waitForVideoReady(videoEl, timeoutMs = 3000) {
        if (videoEl.readyState >= 3) {
            console.log('[PiP] Video already ready, readyState:', videoEl.readyState);
            return;
        }

        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                console.log('[PiP] Wait timeout, proceeding anyway. readyState:', videoEl.readyState);
                resolve(); // Proceed anyway after timeout
            }, timeoutMs);

            const onReady = () => {
                clearTimeout(timeout);
                console.log('[PiP] Video ready via event, readyState:', videoEl.readyState);
                resolve();
            };

            videoEl.addEventListener('canplay', onReady, { once: true });
            videoEl.addEventListener('canplaythrough', onReady, { once: true });

            // Check again in case state changed
            if (videoEl.readyState >= 3) {
                clearTimeout(timeout);
                resolve();
            }
        });
    }

    // Helper: Load video with timeout
    async loadVideoWithTimeout(videoEl, url, timeoutMs = 5000) {
        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                console.log('[PiP] Load timeout, proceeding. readyState:', videoEl.readyState);
                resolve(); // Proceed anyway
            }, timeoutMs);

            const onLoaded = () => {
                clearTimeout(timeout);
                console.log('[PiP] Video loaded, readyState:', videoEl.readyState);
                resolve();
            };

            const onError = (e) => {
                clearTimeout(timeout);
                console.error('[PiP] Video load error:', e);
                reject(e);
            };

            videoEl.addEventListener('loadeddata', onLoaded, { once: true });
            videoEl.addEventListener('canplay', onLoaded, { once: true });
            videoEl.addEventListener('error', onError, { once: true });

            videoEl.src = url;
        });
    }

    async playNextChunk() {
        // Skip legacy playback when HLS is active
        if (this.useHLS && this.hlsInitialized) {
            // HLS.js handles playback, don't use legacy double-buffer
            return;
        }

        // Prevent multiple simultaneous calls - set flag IMMEDIATELY
        if (this._playingTransition) {
            console.log('[PiP] Transition already in progress, skipping playNextChunk');
            return;
        }
        this._playingTransition = true;  // Lock immediately

        console.log(`[PiP] playNextChunk called. Looking for chunk ${this.currentChunkIndex}`);

        const nextChunk = this.videoQueue.find(c =>
            c.chunk_index === this.currentChunkIndex && c.status === 'completed'
        );

        if (!nextChunk) {
            this.isPlaying = false;
            this._playingTransition = false;  // Release lock - no chunk to play
            const hasPending = this.videoQueue.some(c =>
                c.chunk_index >= this.currentChunkIndex &&
                (c.status === 'queued' || c.status === 'processing')
            );

            console.log(`[PiP] Chunk ${this.currentChunkIndex} not ready. hasPending:`, hasPending,
                'Queue:', this.videoQueue.map(c => `${c.chunk_index}:${c.status}`).join(', '));

            if (hasPending) {
                // DON'T show loop - keep last frame visible while waiting
                this.statusElement.textContent = 'Buffering next chunk...';
            } else {
                // Truly idle - now show the loop
                this.showLoop();
                this.statusElement.textContent = 'Ready - Idle';
            }
            return;
        }

        this.isPlaying = true;
        // _playingTransition already set at function start
        this.statusElement.textContent = `Playing chunk ${nextChunk.chunk_index + 1}`;

        try {
            const chunk_id = `${this.sessionId}_chunk_${nextChunk.chunk_index}`;
            const videoUrl = `/api/video/stream/${chunk_id}?t=${Date.now()}`;

            const { active, inactive } = this.getPlayers();

            // Check if already preloaded in inactive player
            if (nextChunk.preloaded && inactive.src && inactive.src.includes(chunk_id)) {
                console.log('[PiP] Using preloaded chunk:', this.currentChunkIndex, 'readyState:', inactive.readyState);

                // Wait for video to be ready with timeout
                await this.waitForVideoReady(inactive, 3000);

                // Swap players - inactive becomes active
                this.swapPlayers();
                await this.getPlayers().active.play();
            } else {
                // Not preloaded - load into inactive, then swap
                console.log('[PiP] Loading chunk:', this.currentChunkIndex);

                // Ensure inactive is muted during load
                inactive.muted = true;

                await this.loadVideoWithTimeout(inactive, videoUrl, 5000);

                // Swap players (swapPlayers will unmute the new active)
                this.swapPlayers();
                await this.getPlayers().active.play();
            }

            this._playingTransition = false;
            console.log(`[PiP] Now playing chunk ${this.currentChunkIndex}, activePlayer: ${this.activePlayer}`);

            // Preload NEXT chunk while this one plays
            this.preloadNextChunk();

        } catch (error) {
            console.error('[PiP] Play error:', error);
            this.statusElement.textContent = 'Playback error - retrying...';
            this.isPlaying = false;
            this._playingTransition = false;
            setTimeout(() => this.playNextChunk(), 500);
        }
    }

    preloadNextChunk() {
        /**
         * Preload the next chunk in the inactive player for seamless transitions.
         */
        const nextIndex = this.currentChunkIndex + 1;
        const nextChunk = this.videoQueue.find(c =>
            c.chunk_index === nextIndex && c.status === 'completed'
        );

        if (!nextChunk) {
            console.log(`[PiP] Cannot preload chunk ${nextIndex} - not completed yet`);
            return;
        }
        if (nextChunk.preloaded) {
            console.log(`[PiP] Chunk ${nextIndex} already preloaded`);
            return;
        }

        const chunk_id = `${this.sessionId}_chunk_${nextChunk.chunk_index}`;
        const videoUrl = `/api/video/stream/${chunk_id}?t=${Date.now()}`;

        const { inactive } = this.getPlayers();

        // Ensure inactive player is paused, muted, and clean before loading
        inactive.pause();
        inactive.muted = true;  // Keep muted until it becomes active

        console.log('[PiP] Preloading next chunk:', nextIndex);
        inactive.src = videoUrl;
        inactive.load();
        nextChunk.preloaded = true;
        nextChunk.preloadedUrl = videoUrl;
    }

    playPrevious() {
        if (this.currentChunkIndex > 0) {
            this.currentChunkIndex--;
            this.getPlayers().active.pause();
            this.isPlaying = false;
            this.playNextChunk();
        }
    }

    playNext() {
        this.currentChunkIndex++;
        this.getPlayers().active.pause();
        this.isPlaying = false;
        this.playNextChunk();
    }

    stop() {
        this.getPlayers().active.pause();
        this.isPlaying = false;
        this.showLoop();
        this.statusElement.textContent = 'Stopped - Idle';
    }

    updateQueueInfo() {
        const queued = this.videoQueue.filter(c => c.status === 'queued').length;
        const processing = this.videoQueue.filter(c => c.status === 'processing').length;
        const completed = this.videoQueue.filter(c => c.status === 'completed').length;
        this.queueInfoElement.textContent =
            `Queue: ${queued} queued, ${processing} processing, ${completed} ready`;
    }
}

// Export for module usage (if needed in future)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PiPVideoPlayer;
}
