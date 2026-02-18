/**
 * MeetingRecorder - Browser audio capture for Iris meeting transcription
 *
 * Captures audio via getUserMedia(), records in 5-minute chunks using
 * MediaRecorder, and uploads each chunk to /api/meeting/upload-chunk.
 *
 * Usage:
 *   const recorder = new MeetingRecorder();
 *   await recorder.start(meetingId);
 *   // ... recording happens ...
 *   recorder.stop();
 */

class MeetingRecorder {
    constructor() {
        this.meetingId = null;
        this.mediaRecorder = null;
        this.audioStream = null;
        this.chunkIndex = 0;
        this.isRecording = false;
        this.startTime = null;
        this.elapsedTimer = null;

        // Chunk rotation interval (5 minutes in ms)
        this.chunkDurationMs = 5 * 60 * 1000;
        this.chunkRotationTimer = null;

        // Current chunk data
        this.currentChunks = [];

        // UI elements (set after DOM ready)
        this.btnEl = null;
        this.statusEl = null;
        this.timerEl = null;
    }

    /**
     * Start recording audio for a meeting.
     * @param {number} meetingId - The meeting ID from the database
     */
    async start(meetingId) {
        if (this.isRecording) {
            console.warn('[MeetingRecorder] Already recording');
            return;
        }

        this.meetingId = meetingId;
        this.chunkIndex = 0;
        this.startTime = Date.now();

        try {
            // Request microphone access
            this.audioStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    sampleRate: 16000,
                    echoCancellation: true,
                    noiseSuppression: true
                }
            });

            // Pause IrisVOX if active (prevent STT from firing during meeting)
            if (typeof IrisVOX !== 'undefined' && typeof IrisVOX.isActive === 'function' && IrisVOX.isActive()) {
                this._voxWasActive = true;
                IrisVOX.vox_button_toggle();
                console.log('[MeetingRecorder] Paused IrisVOX');
            } else {
                console.log('[MeetingRecorder] IrisVOX not active or not available');
            }

            this._startRecorderChunk();
            this._scheduleChunkRotation();
            this.isRecording = true;

            // Start elapsed time display
            this._startTimer();
            this._updateUI('recording');

            console.log(`[MeetingRecorder] Recording started for meeting #${meetingId}`);

        } catch (err) {
            console.error('[MeetingRecorder] Failed to start:', err);
            this._updateUI('error');
            // Show user-visible error
            alert(`Meeting recording failed to start: ${err.message || err}\n\nPlease check microphone permissions.`);
            throw err;
        }
    }

    /**
     * Stop recording and trigger processing.
     */
    async stop() {
        if (!this.isRecording) {
            console.warn('[MeetingRecorder] Not recording');
            return;
        }

        this.isRecording = false;

        // Stop chunk rotation
        if (this.chunkRotationTimer) {
            clearTimeout(this.chunkRotationTimer);
            this.chunkRotationTimer = null;
        }

        // Stop elapsed timer
        this._stopTimer();

        // Stop the current MediaRecorder (triggers dataavailable -> upload)
        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            // Wait for the final chunk to be uploaded
            await new Promise(resolve => {
                this.mediaRecorder.onstop = async () => {
                    await this._uploadChunk();
                    resolve();
                };
                this.mediaRecorder.stop();
            });
        }

        // Stop audio stream
        if (this.audioStream) {
            this.audioStream.getTracks().forEach(track => track.stop());
            this.audioStream = null;
        }

        // Resume IrisVOX if it was active before
        if (this._voxWasActive) {
            if (typeof IrisVOX !== 'undefined' && typeof IrisVOX.isActive === 'function' && !IrisVOX.isActive()) {
                IrisVOX.vox_button_toggle();
                console.log('[MeetingRecorder] Resumed IrisVOX');
            }
            this._voxWasActive = false;
        }

        // Trigger processing via API
        try {
            const resp = await fetch(`/api/meeting/process/${this.meetingId}`, { method: 'POST' });
            const data = await resp.json();
            console.log(`[MeetingRecorder] Processing triggered:`, data);
        } catch (err) {
            console.error('[MeetingRecorder] Failed to trigger processing:', err);
        }

        this._updateUI('stopped');
        console.log(`[MeetingRecorder] Recording stopped. ${this.chunkIndex} chunks uploaded.`);
    }

    /**
     * Get current recording status.
     */
    getStatus() {
        return {
            isRecording: this.isRecording,
            meetingId: this.meetingId,
            chunkIndex: this.chunkIndex,
            elapsed: this.startTime ? Math.floor((Date.now() - this.startTime) / 1000) : 0
        };
    }

    // ========================================================================
    // INTERNAL METHODS
    // ========================================================================

    _startRecorderChunk() {
        // Pick a supported MIME type
        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : MediaRecorder.isTypeSupported('audio/webm')
                ? 'audio/webm'
                : 'audio/ogg;codecs=opus';

        this.mediaRecorder = new MediaRecorder(this.audioStream, {
            mimeType: mimeType,
            audioBitsPerSecond: 64000
        });

        this.currentChunks = [];

        this.mediaRecorder.ondataavailable = (event) => {
            if (event.data && event.data.size > 0) {
                this.currentChunks.push(event.data);
            }
        };

        // Collect data every 10 seconds for progress tracking
        this.mediaRecorder.start(10000);
    }

    _scheduleChunkRotation() {
        this.chunkRotationTimer = setTimeout(async () => {
            if (!this.isRecording) return;

            // Stop current recorder to finalize chunk
            if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
                await new Promise(resolve => {
                    this.mediaRecorder.onstop = async () => {
                        await this._uploadChunk();
                        resolve();
                    };
                    this.mediaRecorder.stop();
                });
            }

            // Start new chunk
            if (this.isRecording && this.audioStream) {
                this._startRecorderChunk();
                this._scheduleChunkRotation();
            }
        }, this.chunkDurationMs);
    }

    async _uploadChunk() {
        if (this.currentChunks.length === 0) return;

        const blob = new Blob(this.currentChunks, { type: this.mediaRecorder?.mimeType || 'audio/webm' });
        this.currentChunks = [];

        const formData = new FormData();
        formData.append('file', blob, `chunk_${this.chunkIndex}.webm`);
        formData.append('meeting_id', this.meetingId);
        formData.append('chunk_index', this.chunkIndex);

        try {
            const resp = await fetch('/api/meeting/upload-chunk', {
                method: 'POST',
                body: formData
            });
            const data = await resp.json();
            console.log(`[MeetingRecorder] Chunk ${this.chunkIndex} uploaded (${(blob.size / 1024).toFixed(0)} KB)`);
            this.chunkIndex++;
            this._updateChunkCount();
        } catch (err) {
            console.error(`[MeetingRecorder] Failed to upload chunk ${this.chunkIndex}:`, err);
        }
    }

    _startTimer() {
        this.elapsedTimer = setInterval(() => {
            if (this.timerEl && this.startTime) {
                const elapsed = Math.floor((Date.now() - this.startTime) / 1000);
                const mins = Math.floor(elapsed / 60);
                const secs = elapsed % 60;
                this.timerEl.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
            }
        }, 1000);
    }

    _stopTimer() {
        if (this.elapsedTimer) {
            clearInterval(this.elapsedTimer);
            this.elapsedTimer = null;
        }
    }

    _updateUI(state) {
        if (!this.btnEl) return;

        switch (state) {
            case 'recording':
                this.btnEl.title = 'Meeting recording in progress (click to stop)';
                this.btnEl.innerHTML = '<span style="color: #ff4444;">&#9899;</span> <span class="pip-btn-text">REC</span>';
                this.btnEl.classList.add('meeting-recording');
                if (this.statusEl) this.statusEl.style.display = 'flex';
                break;
            case 'stopped':
                this.btnEl.title = 'Start meeting recording';
                this.btnEl.innerHTML = '<span class="pip-btn-icon">&#127908;</span><span class="pip-btn-text"> Meet</span>';
                this.btnEl.classList.remove('meeting-recording');
                if (this.statusEl) this.statusEl.style.display = 'none';
                if (this.timerEl) this.timerEl.textContent = '0:00';
                break;
            case 'error':
                this.btnEl.title = 'Recording failed - check microphone permissions';
                break;
        }
    }

    _updateChunkCount() {
        const chunkEl = document.getElementById('meetingChunkCount');
        if (chunkEl) {
            chunkEl.textContent = `${this.chunkIndex} chunks`;
        }
    }
}

// Global singleton
const meetingRecorder = new MeetingRecorder();
