//Namespace all VOX code under IrisVOX
 window.IrisVOX = (() => {
  let mediaStream;
  let mediaRecorder;
  let audioContext;
  let analyser;
  let dataArray;
  let isRecording = false;
  let chunks = [];
  let vbt = false
  let voxSwitch = true

  // === VOX PARAMETERS (loaded from server, with defaults) ===
  let VOX_THRESHOLD = 0.025;
  let VOX_MIN_SPEECH_MS = 3000;
  let VOX_SILENCE_HANG_MS = 5000;

  let speaking = false;
  let speechStartTime = 0;
  let silenceStartTime = null;

  // === Pause flag ===
  let voxPaused = false;

  // === Load settings from localStorage or server ===
  function applyVoxSettings(config) {
    const newThreshold = config.vox_threshold || 0.025;
    const newSilence = config.vox_silence_ms || 5000;
    const newMinSpeech = config.vox_min_speech_ms || 3000;

    if (newThreshold !== VOX_THRESHOLD || newSilence !== VOX_SILENCE_HANG_MS || newMinSpeech !== VOX_MIN_SPEECH_MS) {
      console.log(`[VOX] Settings updated: threshold=${newThreshold}, silence=${newSilence}ms, minSpeech=${newMinSpeech}ms`);
    }

    VOX_THRESHOLD = newThreshold;
    VOX_SILENCE_HANG_MS = newSilence;
    VOX_MIN_SPEECH_MS = newMinSpeech;
  }

  async function loadVoxSettings() {
    // First check localStorage for immediate settings
    const cached = localStorage.getItem('irisVoxConfig');
    if (cached) {
      try {
        applyVoxSettings(JSON.parse(cached));
      } catch (e) {}
    }

    // Then fetch from server to ensure sync
    try {
      const response = await fetch('/api/admin/stt/config');
      const data = await response.json();
      if (data.success) {
        applyVoxSettings(data.config);
        localStorage.setItem('irisVoxConfig', JSON.stringify(data.config));
      }
    } catch (e) {
      console.warn('[VOX] Failed to load settings from server:', e);
    }
  }

  // Listen for localStorage changes from other tabs (admin panel)
  window.addEventListener('storage', (e) => {
    if (e.key === 'irisVoxConfig' && e.newValue) {
      try {
        applyVoxSettings(JSON.parse(e.newValue));
      } catch (err) {}
    }
  });

  // Load settings on init
  loadVoxSettings();
  
  function vox_button_toggle() {
    const voxToggle = document.getElementById("voxToggle")
    if (vbt){
      voxToggle.innerHTML = "🔇"
      vbt = false
      disableListening()
      return
    }
    else
      voxToggle.innerHTML = "👂🏼"
      console.log("vox on")
      vbt = true
      resumeListening()
      return
    }



  // === Indicator and VU meter ===
  function setVoxIndicator(color, label) {
    const indicator = document.getElementById("vox-indicator");
    const labelSpan = document.getElementById("vox-label");
    if (indicator) indicator.style.backgroundColor = color;
    if (labelSpan) labelSpan.textContent = label;
  }

  function setVuMeter(levelPercent, color) {
    const vuFill = document.getElementById("vu-fill");
    if (vuFill) {
      vuFill.style.width = levelPercent + "%";
      vuFill.style.backgroundColor = color;
    }
  }

   function disableListening() {
    voxPaused = true;
       console.log("vox disable")
       setVoxIndicator("grey", "off");
       setVuMeter(100, "grey");
       console.log("🔇 VOX off (mic ignored).");
       stopVox()

  }

   function pauseListening() {
    voxPaused = true;
      console.log("vox pause")
      setVoxIndicator("orange", "...paused");
      setVuMeter(100, "orange");
      console.log("🔇 VOX paused (mic ignored).");
      stopVox()
  }

  function resumeListening() {
    voxPaused = false;
    if (vbt){
      setVoxIndicator("green", "listening");
      setVuMeter(0, "limegreen");
      console.log("🎙️ VOX resumed (mic live).");
      startVox()
    }
    else {disableListening()}
   

  }

  async function startVox() {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });

      audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(mediaStream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      dataArray = new Float32Array(analyser.fftSize);
      source.connect(analyser);

   //   console.log("🎙️ VOX listening started…");
   //   setVoxIndicator("green", "listening");
      monitorVolume();
    } catch (err) {
      console.error("❌ Failed to start VOX:", err);
      setVoxIndicator("gray", "error");
    }
  }

  function monitorVolume() {
    if (voxPaused) {
      // Freeze VU meter orange while Iris is talking
      //setVuMeter(100, "orange");
      //setVoxIndicator("orange", "paused");

      // Do not start or stop recording while paused
      requestAnimationFrame(monitorVolume);
      return;
    }


    analyser.getFloatTimeDomainData(dataArray);

    let sumSquares = 0;
    for (let i = 0; i < dataArray.length; i++) {
      sumSquares += dataArray[i] * dataArray[i];
    }
    const rms = Math.sqrt(sumSquares / dataArray.length);
    const now = performance.now();

    // === Update MIC VU meter ===
    let level = Math.min(100, Math.max(0, (rms / 0.2) * 100));
    if (rms > VOX_THRESHOLD) {
      setVuMeter(level, "purple");
    } else {
      setVuMeter(level, "limegreen");
    }

    // === Speech detection ===
    if (rms > VOX_THRESHOLD) {
      // ALWAYS reset silence timer when sound is detected (fixes premature cutoff bug)
      silenceStartTime = null;

      if (!speaking) {
        speaking = true;
        speechStartTime = now;
        console.log("🎤 Speech detected — starting recorder…");
        setVoxIndicator("red", "recording");
        startRecorder();
      }
    } else {
      if (speaking) {
        if (silenceStartTime === null) silenceStartTime = now;
        if (now - silenceStartTime > VOX_SILENCE_HANG_MS) {
          speaking = false;
          console.log("🤫 Long silence — stopping recorder…");
          setVoxIndicator("green", "listening");
          stopRecorder();
        }
      }
    }

    requestAnimationFrame(monitorVolume);
  }

  function startRecorder() {
    chunks = [];
    mediaRecorder = new MediaRecorder(mediaStream);

    mediaRecorder.ondataavailable = e => {
      if (e.data.size > 0) chunks.push(e.data);
    };

    mediaRecorder.onstop = async () => {
      if (!chunks.length) return;

      // Skip STT upload if meeting is recording (meeting recorder handles its own audio)
      if (typeof meetingRecorder !== 'undefined' && meetingRecorder.isRecording) {
        console.log("⏸️ Meeting recording active - skipping STT upload");
        return;
      }

      const blob = new Blob(chunks, { type: "audio/webm;codecs=opus" });
      const formData = new FormData();
      formData.append("file", blob, "speech.webm");

      console.log("⬆️ Uploading VOX audio…");
      const res = await fetch("/stt-upload", { method: "POST", body: formData });

      if (!res.ok) {
        console.error("❌ STT upload failed:", res.status);
        return;
      }

      const data = await res.json();
      const transcript = (data.transcript || "").trim();
      console.log("Transcript:", transcript);

      if (transcript.length > 0) {
          if (transcript !== "[BLANK_AUDIO]")
          {
              console.log("dispatching event...")
              // Dispatch custom event with transcript
              window.dispatchEvent(new CustomEvent('voiceTranscript', { 
              detail: { transcript: transcript } 
            }));
          }
          else
          {
            console.log("supressing blank audio capure")
          }
      }
    };

    mediaRecorder.start();
    isRecording = true;
  }

  function stopRecorder() {
    if (mediaRecorder && isRecording) {
      isRecording = false;
      mediaRecorder.stop();
    }
  }

  async function stopVox() {
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop());
      mediaStream = null;
    }
    if (audioContext) {
      audioContext.close();
      audioContext = null;
    }
    //setVoxIndicator("gray", "idle");
    //setVuMeter(0, "gray");
    //console.log("🛑 VOX stopped.");
  }

  // Check if VOX is currently active (for meeting mode integration)
  function isActive() {
    return vbt;
  }

  return { startVox, stopVox, pauseListening, resumeListening, disableListening, vox_button_toggle, voxPaused, loadVoxSettings, isActive };
})();


