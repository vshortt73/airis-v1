/**
 * TTSQueue - Text-to-Speech and Video Queue System
 * Dual queue architecture: separates rendering from playback for smooth audio
 *
 * Dependencies: None (standalone class)
 * Global instances: ttsQueue (created after DOM load)
 */

class TTSQueue {
    constructor() {
        // Text batching (unchanged)
        this.partialSentence = '';   // Buffer for incomplete sentences
        this.processedText = '';      // Track what we've already processed
        this.sentenceBatch = [];      // Batch sentences before sending
        this.maxTokens = 375;         // XTTS max is 400, use 375 for safety

        // Dual queue system for parallel rendering and playback
        this.renderQueue = [];        // Text items waiting to be rendered by XTTS
        this.playbackQueue = [];      // Rendered audio blobs ready to play
        this.isRendering = false;     // Is render worker active?
        this.isPlaying = false;       // Is playback worker active?
        this.currentAudio = null;     // Currently playing audio element
        this.enabled = false;

        // Video streaming integration
        console.log('[TTS] Initializing video streaming support...');
        this.videoChannel = new BroadcastChannel('iris-video');
        this.videoSessionId = null;
        this.videoPlayerOpen = false;
        this.chunkIndex = 0;
        // Streaming video API (real-time video generation)
        // Each segment is a complete MP4 with audio - plays in sequence
        this.useStreamingVideo = true;

        // Server-side TTS routing (when enabled, server handles sentence extraction)
        this.serverSideRoutingEnabled = false;
        this.serverAudioComplete = true;  // True when no server audio expected
        this.pendingAudioMeta = null;  // Metadata for next binary audio chunk

        console.log('[TTS] Initial state - sessionId:', this.videoSessionId, 'playerOpen:', this.videoPlayerOpen, 'streaming:', this.useStreamingVideo);

        // Listen for all video messages via BroadcastChannel
        this.videoChannel.onmessage = (event) => {
            console.log('[TTS] Received BroadcastChannel message:', event.data);
            const msgType = event.data.type;

            if (msgType === 'video-session-started') {
                this.videoSessionId = event.data.sessionId;
                this.chunkIndex = 0;
                console.log('[TTS] Video session started:', this.videoSessionId);
            } else if (msgType === 'video-session-ended') {
                this.videoSessionId = null;
                console.log('[TTS] Video session ended');
            } else if (msgType === 'player-ready') {
                this.videoPlayerOpen = true;
                console.log('[TTS] Video player ready');
            } else if (msgType === 'player-closed') {
                this.videoPlayerOpen = false;
                console.log('[TTS] Video player closed');
            }
        };
    }

    // Estimate token count (words * 1.3 is a reasonable approximation)
    estimateTokens(text) {
        const words = text.trim().split(/\s+/).length;
        return Math.ceil(words * 1.3);
    }

    enable() {
        this.enabled = true;
        console.log('[TTS] Voice enabled');
    }

    disable() {
        this.enabled = false;
        this.stop();
        console.log('[TTS] Voice disabled');
    }

    // Clean markdown from text before TTS
    cleanMarkdown(text) {
        // Remove markdown bold/italic
        text = text.replace(/\*\*\*(.+?)\*\*\*/g, '$1');  // ***bold italic***
        text = text.replace(/\*\*(.+?)\*\*/g, '$1');      // **bold**
        text = text.replace(/\*(.+?)\*/g, '$1');          // *italic*
        text = text.replace(/__(.+?)__/g, '$1');          // __bold__
        text = text.replace(/_(.+?)_/g, '$1');            // _italic_

        // Remove markdown headers
        text = text.replace(/^#{1,6}\s+/gm, '');

        // Remove markdown horizontal rules
        text = text.replace(/^---+$/gm, '');
        text = text.replace(/^\*\*\*+$/gm, '');

        // Remove markdown links but keep text
        text = text.replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1');

        // Replace markdown code blocks with a spoken indicator
        text = text.replace(/```[\s\S]*?```/g, ' - you can see the code in our conversation - ');

        // Remove inline code (just remove it entirely, don't speak variable names)
        text = text.replace(/`[^`]+`/g, '');

        // Remove markdown list markers
        text = text.replace(/^[\*\-\+]\s+/gm, '');

        // Remove Unicode emojis (they don't speak well)
        text = text.replace(/[\u{1F300}-\u{1F9FF}]/gu, '');

        // Remove text-based emoticons/emojis
        text = text.replace(/[:\;]-?[\)\(DPpOo\[\]\/\\|3<>]|<3|XD|xD/g, '');

        // Replace IP addresses with spoken format
        text = text.replace(/\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b/g,
            '$1 dot $2 dot $3 dot $4');

        return text;
    }

    // Extract complete sentences from text
    extractSentences(text) {
        // Clean markdown first
        text = this.cleanMarkdown(text);

        // Improved sentence detection that avoids splitting on:
        // - Numbers in lists (1., 2., 3.)
        // - Decimals (3.14, 2.0)
        // - Abbreviations (Dr., Mr., etc.)
        // Only split on sentence-ending punctuation followed by space + capital letter or end of string
        const sentences = [];

        // Split on . ! ? but be smart about it
        // Match sentence ending punctuation followed by space and capital letter, or end of string
        const parts = text.split(/([.!?]+(?:\s+(?=[A-Z])|$))/);

        let currentSentence = '';
        for (let i = 0; i < parts.length; i++) {
            const part = parts[i];
            if (!part) continue;

            currentSentence += part;

            // If this part ends with sentence punctuation, consider it complete
            if (/[.!?]+$/.test(part.trim())) {
                const trimmed = currentSentence.trim();
                // Ignore very short "sentences" like just numbers
                if (trimmed.length > 2 && !/^\d+\.?$/.test(trimmed)) {
                    sentences.push(trimmed);
                }
                currentSentence = '';
            }
        }

        // Add any remaining text
        if (currentSentence.trim().length > 2) {
            sentences.push(currentSentence.trim());
        }

        return sentences.filter(s => s.length > 0);
    }

    // Add text chunk and extract/queue sentences
    addTextChunk(chunk) {
        // Allow processing if TTS is enabled OR video mode is active
        if (!this.enabled && !this.videoSessionId) {
            console.log('[TTS] Chunk received but TTS disabled and no video session, ignoring');
            return;
        }

        console.log('[TTS] Received chunk:', JSON.stringify(chunk));

        // Accumulate the chunk
        this.partialSentence += chunk;
        console.log('[TTS] Partial sentence buffer:', JSON.stringify(this.partialSentence));

        // Try to extract complete sentences
        const sentences = this.extractSentences(this.partialSentence);
        console.log('[TTS] Extracted sentences:', sentences);

        if (sentences.length > 0) {
            // Get the last sentence to check if it's complete
            const lastSentence = sentences[sentences.length - 1];
            const endsWithTerminator = /[.!?]\s*$/.test(this.partialSentence.trim());
            console.log('[TTS] Ends with terminator?', endsWithTerminator);

            if (endsWithTerminator) {
                // All sentences are complete, queue them all
                console.log('[TTS] All sentences complete, queuing all');
                sentences.forEach(sentence => {
                    const trimmed = sentence.trim();
                    if (trimmed && !this.processedText.includes(trimmed)) {
                        this.queueSentence(trimmed);
                        this.processedText += ' ' + trimmed;
                    }
                });
                this.partialSentence = '';
            } else {
                // Last sentence might be incomplete, queue all but last
                console.log('[TTS] Last sentence incomplete, queuing', sentences.length - 1, 'sentences');
                for (let i = 0; i < sentences.length - 1; i++) {
                    const trimmed = sentences[i].trim();
                    if (trimmed && !this.processedText.includes(trimmed)) {
                        this.queueSentence(trimmed);
                        this.processedText += ' ' + trimmed;
                    }
                }
                // Keep the last incomplete sentence in the buffer
                this.partialSentence = lastSentence;
                console.log('[TTS] Keeping incomplete sentence in buffer:', JSON.stringify(lastSentence));
            }
        }
    }

    // Called when streaming is complete to flush any remaining text
    finalize() {
        // Allow finalize if TTS is enabled OR video mode is active
        if (!this.enabled && !this.videoSessionId) {
            console.log('[TTS] Finalize called but TTS disabled and no video session');
            return;
        }

        console.log('[TTS] Finalize called, partial sentence:', JSON.stringify(this.partialSentence));

        // Queue any remaining partial sentence
        if (this.partialSentence.trim()) {
            const remaining = this.partialSentence.trim();
            if (!this.processedText.includes(remaining)) {
                console.log('[TTS] Queuing final partial sentence:', remaining);
                this.queueSentence(remaining);
                this.processedText += ' ' + remaining;
            }
        }

        // Flush any remaining batched sentences
        this.flushBatch();

        this.partialSentence = '';
        console.log('[TTS] Finalize complete');
    }

    // Reset for new message (keeps workers running, just clears text buffers)
    reset() {
        console.log('[TTS] Reset called - clearing text buffers');
        this.partialSentence = '';
        this.processedText = '';
        this.flushBatch();  // Flush any pending batch to render queue
        this.sentenceBatch = [];
    }

    // Add sentence to batch, flush when ready
    queueSentence(sentence) {
        console.log('[TTS] Batching sentence:', sentence.substring(0, 50) + '...');

        // Add to batch
        this.sentenceBatch.push(sentence);

        // Calculate current batch tokens
        const batchText = this.sentenceBatch.join(' ');
        const tokenCount = this.estimateTokens(batchText);

        console.log('[TTS] Batch now has', this.sentenceBatch.length, 'sentences,', tokenCount, 'tokens');

        // Flush conditions vary based on mode:
        // VIDEO MODE: Flush aggressively (~50 tokens / 2 sentences) to keep
        //   small chunks flowing through the pipeline smoothly
        // AUDIO MODE: Flush at comfortable batch size (150+ tokens / 5 sentences)

        const isVideoMode = this.videoSessionId && this.videoPlayerOpen;

        if (tokenCount >= this.maxTokens) {
            // Remove the last sentence that pushed us over
            const lastSentence = this.sentenceBatch.pop();

            // Flush the batch without the last sentence
            this.flushBatch();

            // Start new batch with the sentence that didn't fit
            if (lastSentence) {
                this.sentenceBatch = [lastSentence];
            }
        } else if (isVideoMode && (tokenCount >= 50 || this.sentenceBatch.length >= 2)) {
            // VIDEO MODE: Flush after 2 sentences or ~50 tokens (~12-15 words)
            // Small chunks = fast generation = smooth video pipeline
            this.flushBatch();
        } else if (tokenCount >= 150 || this.sentenceBatch.length >= 5) {
            // AUDIO MODE: Normal flush at comfortable batch size
            this.flushBatch();
        }
    }

    // Clean text of markdown formatting for TTS
    cleanTextForTTS(text) {
        return text
            // Remove markdown formatting
            .replace(/\*\*/g, '')        // Bold
            .replace(/\*/g, '')          // Italic
            .replace(/_/g, ' ')          // Underscores to spaces
            .replace(/`/g, '')           // Code backticks
            .replace(/#+/g, '')          // Hash marks (XTTS says "hash hash hash")
            .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')  // Links - keep text
            // Collapse multiple spaces/newlines into single space
            .replace(/[\s\n]+/g, ' ')
            .trim();
    }

    // Flush current batch to render queue
    flushBatch() {
        if (this.sentenceBatch.length === 0) return;

        const rawBatchText = this.sentenceBatch.join(' ');
        const batchText = this.cleanTextForTTS(rawBatchText);
        const tokenCount = this.estimateTokens(batchText);

        // Skip if cleaned text is empty
        if (!batchText) {
            console.log('[TTS] Skipping empty batch after cleaning');
            this.sentenceBatch = [];
            return;
        }

        console.log('[TTS] Flushing batch:', this.sentenceBatch.length, 'sentences,', tokenCount, 'tokens');
        console.log('[TTS] Batch text:', batchText.substring(0, 100) + '...');

        // Check if video mode - route directly to video (no pre-rendering needed)
        if (this.videoSessionId && this.videoPlayerOpen) {
            console.log('[TTS] Routing to VIDEO (video mode active)');
            this.speakWithVideo(batchText);
            this.sentenceBatch = [];
            return;
        }

        // Audio mode: add to render queue for parallel rendering
        this.renderQueue.push(batchText);
        this.sentenceBatch = [];

        // Start render worker if not already running
        this.startRenderWorker();
    }

    // Render worker: continuously fetches audio from XTTS
    // Runs in parallel with playback - renders ahead while audio plays
    async startRenderWorker() {
        if (this.isRendering) {
            console.log('[TTS] Render worker already running');
            return;
        }

        this.isRendering = true;
        console.log('[TTS] Render worker started, queue depth:', this.renderQueue.length);

        while (this.renderQueue.length > 0 && this.enabled) {
            const text = this.renderQueue.shift();
            console.log('[TTS] Rendering:', text.substring(0, 50) + '...');

            try {
                const audioBlob = await this.renderAudio(text);
                console.log('[TTS] Rendered audio:', audioBlob.size, 'bytes');

                // Add to playback queue
                this.playbackQueue.push({ blob: audioBlob, text: text });

                // Start playback worker if not running (plays first audio immediately)
                this.startPlaybackWorker();

            } catch (error) {
                console.error('[TTS] Render error:', error);
            }
        }

        this.isRendering = false;
        console.log('[TTS] Render worker finished');
    }

    // Render audio via XTTS (fetch only, no playback)
    async renderAudio(text) {
        const response = await fetch('/api/tts/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        });

        if (!response.ok) {
            throw new Error(`TTS server error: ${response.status}`);
        }

        return await response.blob();
    }

    // Playback worker: plays audio sequentially from ready queue
    // Starts as soon as first audio is ready, continues without gaps
    async startPlaybackWorker() {
        if (this.isPlaying) {
            console.log('[TTS] Playback worker already running');
            return;
        }

        this.isPlaying = true;
        console.log('[TTS] Playback worker started');

        while (this.enabled) {
            // Wait for audio to be available
            if (this.playbackQueue.length === 0) {
                // Check if more audio is coming
                // For server-side routing: wait for serverAudioComplete flag
                // For browser-side routing: check isRendering and renderQueue
                const moreAudioComing = this.serverSideRoutingEnabled
                    ? !this.serverAudioComplete
                    : (this.isRendering || this.renderQueue.length > 0);

                if (!moreAudioComing) {
                    // No more audio coming, we're done
                    break;
                }
                // Wait a bit for more audio
                await new Promise(resolve => setTimeout(resolve, 50));
                continue;
            }

            const { blob, text } = this.playbackQueue.shift();
            console.log('[TTS] Playing:', text.substring(0, 50) + '...');

            try {
                const audioUrl = URL.createObjectURL(blob);
                await this.playAudio(audioUrl);
                URL.revokeObjectURL(audioUrl);
                console.log('[TTS] Playback complete');
            } catch (error) {
                console.error('[TTS] Playback error:', error);
            }
        }

        this.isPlaying = false;
        console.log('[TTS] Playback worker finished');
    }

    // Split text into smaller chunks for faster first-video playback
    // Target: ~10-12 words per chunk (~3 seconds of audio)
    splitTextForVideo(text, maxWords = 12) {
        const words = text.trim().split(/\s+/);
        if (words.length <= maxWords) {
            return [text];  // Already small enough
        }

        const chunks = [];
        let currentChunk = [];

        for (const word of words) {
            currentChunk.push(word);

            // Check for natural break points (end of sentence/clause)
            const isBreakPoint = /[.!?,;:]$/.test(word);
            const chunkLength = currentChunk.length;

            // Flush at natural breaks if we have enough words, or at max
            if ((isBreakPoint && chunkLength >= 6) || chunkLength >= maxWords) {
                chunks.push(currentChunk.join(' '));
                currentChunk = [];
            }
        }

        // Don't leave tiny remnants - append to last chunk if too small
        if (currentChunk.length > 0) {
            if (currentChunk.length < 4 && chunks.length > 0) {
                chunks[chunks.length - 1] += ' ' + currentChunk.join(' ');
            } else {
                chunks.push(currentChunk.join(' '));
            }
        }

        return chunks;
    }

    // Queue a single video chunk (internal helper)
    async queueSingleVideoChunk(text, chunkIndex) {
        const payload = {
            session_id: this.videoSessionId,
            text: text,
            chunk_index: chunkIndex
        };
        console.log('[TTS] Sending to /api/video/queue-chunk:', payload);

        const response = await fetch('/api/video/queue-chunk', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });

        console.log('[TTS] Response status:', response.status);

        if (!response.ok) {
            const errorText = await response.text();
            console.error('[TTS] Error response:', errorText);
            throw new Error(`Video queue error: ${response.status}`);
        }

        const result = await response.json();
        console.log('[TTS] Video chunk queued:', result);

        // Notify video player via BroadcastChannel (for external windows)
        this.videoChannel.postMessage({
            type: 'queue-chunk',
            data: {
                chunk_index: chunkIndex,
                text: text,
                status: 'queued'
            }
        });

        // Also notify in-page PiP player via custom event
        window.dispatchEvent(new CustomEvent('iris-video-chunk', {
            detail: {
                chunk_index: chunkIndex,
                text: text,
                status: 'queued'
            }
        }));
        console.log('[TTS] Notified video player of chunk:', chunkIndex);

        return result;
    }

    // Queue chunk for video generation
    async speakWithVideo(text) {
        try {
            console.log('[TTS] speakWithVideo() called');
            console.log('[TTS] Session ID:', this.videoSessionId);
            console.log('[TTS] Text:', text.substring(0, 50) + '...');

            // Use streaming API if available (FLOAT streams video as it generates)
            // This is faster because:
            // 1. No artificial text splitting needed
            // 2. FLOAT handles whole audio for better lip sync
            // 3. Segments arrive as they're generated, not after full completion
            if (this.useStreamingVideo && typeof pipPlayer !== 'undefined' && pipPlayer.streamVideo) {
                console.log('[TTS] Using streaming video API');
                // Don't await - let it stream in background
                pipPlayer.streamVideo(text);
                return;
            }

            // Fallback: Legacy chunking approach
            console.log('[TTS] Using legacy chunk-based video');
            const wordCount = text.trim().split(/\s+/).length;

            // ALWAYS split large chunks for smooth video pipeline
            // Target: ~12 words per chunk (~3-4 seconds of video)
            // Generation time: ~0.9 seconds, so pipeline stays ahead
            if (wordCount > 15) {
                console.log(`[TTS] Chunk is large (${wordCount} words) - splitting for smooth playback`);
                const subChunks = this.splitTextForVideo(text, 12);
                console.log(`[TTS] Split into ${subChunks.length} sub-chunks`);

                for (const subChunk of subChunks) {
                    await this.queueSingleVideoChunk(subChunk, this.chunkIndex);
                    this.chunkIndex++;
                }
            } else {
                // Small chunk - queue as-is
                await this.queueSingleVideoChunk(text, this.chunkIndex);
                this.chunkIndex++;
            }

            // Video player handles playback automatically - no waiting needed

        } catch (error) {
            console.error('[TTS] Video chunk error:', error);
            // Fallback to audio-only on error
            console.log('[TTS] Falling back to audio-only');
            this.videoPlayerOpen = false;
            throw error;
        }
    }

    // Play audio and return a promise that resolves when playback ends
    playAudio(url) {
        return new Promise((resolve, reject) => {
            if (this.currentAudio) {
                this.currentAudio.pause();
                this.currentAudio = null;
            }

            const audio = new Audio(url);
            this.currentAudio = audio;

            audio.onended = () => {
                this.currentAudio = null;
                resolve();
            };

            audio.onerror = (error) => {
                this.currentAudio = null;
                reject(error);
            };

            audio.play().catch(reject);
        });
    }

    // Stop all audio and clear all queues
    stop() {
        console.log('[TTS] Stop called - clearing all queues');

        // Stop current audio
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio = null;
        }

        // Clear all queues
        this.renderQueue = [];
        this.playbackQueue = [];
        this.sentenceBatch = [];

        // Reset state
        this.isRendering = false;
        this.isPlaying = false;
        this.partialSentence = '';
        this.processedText = '';

        // Reset server-side audio state
        this.serverAudioComplete = !this.serverSideRoutingEnabled;  // If server routing, expect audio
        this.pendingAudioMeta = null;
    }

    // ============================================
    // SERVER-SIDE TTS ROUTING SUPPORT
    // ============================================
    // These methods handle audio/video chunks received from server
    // when SERVER_SIDE_TTS_ROUTING is enabled.

    // Handle audio chunk from server (base64 encoded)
    async handleAudioChunk(data) {
        if (!this.enabled) {
            console.log('[TTS] Audio chunk received but TTS disabled, ignoring');
            return;
        }

        if (data.is_last) {
            console.log('[TTS] Server-side audio complete');
            this.serverAudioComplete = true;
            return;
        }

        if (!data.audio) {
            console.warn('[TTS] Audio chunk missing audio data');
            return;
        }

        console.log('[TTS] Received audio chunk from server, index:', data.sentence_index);

        // Decode base64 audio and add to playback queue
        try {
            // Use fetch with data URL for robust base64 decoding
            // This is more reliable than atob() for binary data
            const dataUrl = `data:audio/mpeg;base64,${data.audio}`;
            const response = await fetch(dataUrl);
            const audioBlob = await response.blob();

            // Debug: check first bytes to verify data integrity
            const firstBytes = await audioBlob.slice(0, 10).arrayBuffer();
            const hexBytes = Array.from(new Uint8Array(firstBytes)).map(b => b.toString(16).padStart(2, '0')).join('');
            console.log('[TTS] Decoded audio blob:', audioBlob.size, 'bytes, starts with:', hexBytes);

            // Add to playback queue
            this.playbackQueue.push({
                blob: audioBlob,
                text: `Server chunk ${data.sentence_index}`
            });

            // Start playback worker if not running
            this.startPlaybackWorker();
        } catch (error) {
            console.error('[TTS] Failed to decode audio chunk:', error);
        }
    }

    // Handle binary audio data from WebSocket (no base64 encoding)
    handleBinaryAudio(blob) {
        if (!this.enabled) {
            console.log('[TTS] Binary audio received but TTS disabled, ignoring');
            return;
        }

        const meta = this.pendingAudioMeta;
        const sentenceIndex = meta ? meta.sentence_index : '?';
        console.log('[TTS] Binary audio received:', blob.size, 'bytes, index:', sentenceIndex);

        // Create blob with correct MIME type
        const audioBlob = new Blob([blob], { type: 'audio/mpeg' });

        // Add to playback queue
        this.playbackQueue.push({
            blob: audioBlob,
            text: `Server chunk ${sentenceIndex}`
        });

        // Clear pending meta
        this.pendingAudioMeta = null;

        // Start playback worker if not running
        this.startPlaybackWorker();
    }

    // Handle video chunk ready notification from server
    handleVideoChunkReady(data) {
        if (data.is_last) {
            console.log('[TTS] Server-side video complete');
            return;
        }

        // Determine status - server may send 'completed' when video is ready
        const status = data.status || 'queued';
        console.log(`[TTS] Video chunk ${data.chunk_index} from server, status: ${status}`);

        // Notify video player via BroadcastChannel
        this.videoChannel.postMessage({
            type: 'queue-chunk',
            data: {
                chunk_index: data.chunk_index,
                text: data.text,
                status: status,
                video_path: data.video_path,
                session_id: data.session_id
            }
        });

        // Also notify in-page PiP player via custom event
        window.dispatchEvent(new CustomEvent('iris-video-chunk', {
            detail: {
                chunk_index: data.chunk_index,
                text: data.text,
                status: status,
                video_path: data.video_path,
                session_id: data.session_id
            }
        }));
    }

    setServerSideRouting(enabled) {
        this.serverSideRoutingEnabled = enabled;
        console.log('[TTS] Server-side routing:', enabled ? 'enabled' : 'disabled');
    }
}

// Export for module usage (if needed in future)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TTSQueue;
}
