"""
backend/services/audio_analyser.py

Analyses raw audio bytes (webm/wav from browser MediaRecorder) and returns:
  - confidence_score   (0–10)  : derived from pitch variation, energy, speech rate
  - clarity_score      (0–10)  : derived from pause ratio, articulation rate
  - pace_wpm           (int)   : estimated words per minute
  - hesitation_count   (int)   : long pauses (>0.5s) detected
  - pitch_variation    (float) : std-dev of F0 in Hz — low = monotone
  - tone               (str)   : "flat" | "moderate" | "expressive"
  - feedback_notes     (list)  : plain-English coaching points
"""

import io
import numpy as np
import librosa
import tempfile
import os
import subprocess


def _convert_to_wav(audio_bytes: bytes) -> bytes:
    """
    Browser MediaRecorder outputs webm/opus.
    librosa needs wav/mp3/ogg.  Use ffmpeg if available; else try direct load.
    """
    print("Converting audio to WAV format for analysis...")
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f_in:
        f_in.write(audio_bytes)
        f_in_path = f_in.name

    f_out_path = f_in_path.replace(".webm", ".wav")
    print(f"Input audio saved to {f_in_path}, converting to WAV...")

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", f_in_path, "-ar", "16000", "-ac", "1", f_out_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        print(f"Audio converted to WAV at {f_out_path}")
        with open(f_out_path, "rb") as f:
            wav_bytes = f.read()
            print(f"Read {len(wav_bytes)} bytes from converted WAV file.")
    except Exception:
        # ffmpeg not available — try loading webm directly with librosa (may fail)
        wav_bytes = audio_bytes
        print("ffmpeg conversion failed, will attempt to load original audio bytes directly (may fail if format unsupported).")
    finally:
        # Always clean up both temp files, regardless of what succeeded or failed
        if os.path.exists(f_in_path):
            os.unlink(f_in_path)
        if os.path.exists(f_out_path):
            os.unlink(f_out_path)

    return wav_bytes


def analyse_audio(audio_bytes: bytes, transcript: str = "") -> dict:
    """
    Main entry point.  audio_bytes = raw bytes from the browser (webm or wav).
    transcript = the speech-to-text string (used for WPM calculation).
    Returns a dict matching the schema above.
    """
    # ── 1. Load audio ────────────────────────────────────────────────────────
    wav_bytes = _convert_to_wav(audio_bytes)
    print(f"Attempting to load audio for analysis (length: {len(wav_bytes)} bytes)...")
    try:
        y, sr = librosa.load(io.BytesIO(wav_bytes), sr=16000, mono=True)
        print(f"Audio loaded successfully: {len(y)} samples at {sr} Hz")
    except Exception:
        # Fallback: try loading original bytes directly
        try:
            y, sr = librosa.load(io.BytesIO(audio_bytes), sr=16000, mono=True)
        except Exception as e:
            return _fallback_result(f"Could not decode audio: {e}")

    duration_sec = len(y) / sr
    print(f"Audio duration: {duration_sec:.2f} seconds")
    if duration_sec < 1.0:
        return _fallback_result("Audio too short to analyse.")

    # ── 2. Pitch (F0) analysis ───────────────────────────────────────────────
    # pyin gives reliable F0 with voiced/unvoiced detection
    f0, voiced_flag, _ = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),   # ~65 Hz — below normal speech floor
        fmax=librosa.note_to_hz("C7"),   # ~2093 Hz — above normal speech ceiling
        sr=sr,
    )
    print(f"Extracted F0 contour with {np.sum(~np.isnan(f0))} voiced frames out of {len(f0)} total frames.")

    voiced_f0 = f0[voiced_flag & ~np.isnan(f0)]

    if len(voiced_f0) < 5:
        pitch_mean = 0.0
        pitch_std = 0.0
    else:
        pitch_mean = float(np.mean(voiced_f0))
        pitch_std = float(np.std(voiced_f0))

    print(f"Pitch analysis: mean F0 = {pitch_mean:.2f} Hz, std-dev = {pitch_std:.2f} Hz")

    # ── 3. Energy / RMS analysis ─────────────────────────────────────────────
    frame_length = 512
    hop_length = 256
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    rms_mean = float(np.mean(rms))
    rms_std = float(np.std(rms))

    # ── 4. Pause / silence detection ────────────────────────────────────────
    # Mark frames as speech if RMS > 5% of peak
    speech_threshold = 0.05 * float(np.max(rms)) if np.max(rms) > 0 else 0.01
    is_speech = rms > speech_threshold

    # Count transitions silence→speech and measure silence gap lengths
    silence_frames = ~is_speech
    silence_run = 0
    long_pauses = 0          # pauses > 500 ms
    total_silence_frames = 0

    frames_per_500ms = int(0.5 * sr / hop_length)

    run_lengths = []
    current_run = 0
    in_silence = False

    for s in silence_frames:
        if s:
            current_run += 1
            total_silence_frames += 1
        else:
            if in_silence and current_run > 0:
                run_lengths.append(current_run)
                if current_run >= frames_per_500ms:
                    long_pauses += 1
            current_run = 0
        in_silence = bool(s)

    total_frames = len(rms)
    speech_frames = total_frames - total_silence_frames
    speech_ratio = speech_frames / total_frames if total_frames > 0 else 0.5
    pause_ratio = 1.0 - speech_ratio   # fraction of time spent silent
    print(f"Silence analysis: {long_pauses} long pauses (>0.5s), speech ratio = {speech_ratio:.2f}, pause ratio = {pause_ratio:.2f}")

    # ── 5. Articulation rate (speech rate excluding pauses) ──────────────────
    word_count = len(transcript.split()) if transcript.strip() else 0
    print(f"Transcript word count: {word_count}")

    # Use voiced duration as proxy for actual speaking time
    voiced_duration_sec = (speech_frames * hop_length) / sr
    if voiced_duration_sec > 0 and word_count > 0:
        pace_wpm = int((word_count / voiced_duration_sec) * 60)
    else:
        pace_wpm = 0

    # ── 6. Tone label ────────────────────────────────────────────────────────
    # pitch_std < 20 Hz = flat/monotone; 20-50 = moderate; >50 = expressive
    if pitch_std < 20:
        tone = "flat"
    elif pitch_std < 50:
        tone = "moderate"
    else:
        tone = "expressive"

    # ── 7. Score computation ─────────────────────────────────────────────────
    # Confidence score (0–10): rewards pitch variation, consistent energy, low hesitation
    pitch_score = min(pitch_std / 60.0, 1.0)          # normalise: 60 Hz std → full score
    energy_score = min(rms_mean / 0.05, 1.0)           # normalise: 0.05 RMS → full score
    hesitation_penalty = min(long_pauses / 5.0, 1.0)  # 5+ long pauses → full penalty

    confidence_raw = (
        0.40 * pitch_score +
        0.30 * energy_score +
        0.30 * (1.0 - hesitation_penalty)
    )
    confidence_score = round(confidence_raw * 10, 1)
    print(f"Confidence score components: pitch={pitch_score:.2f}, energy={energy_score:.2f}, hesitation_penalty={hesitation_penalty:.2f} → confidence_score={confidence_score:.1f}")
    # Clarity score (0–10): rewards speech ratio, appropriate pace, low pause ratio
    pace_score = _pace_score(pace_wpm)                  # sweet spot 120-160 WPM
    speech_ratio_score = min(speech_ratio / 0.7, 1.0)  # 70%+ speech → full score

    clarity_raw = (
        0.50 * speech_ratio_score +
        0.30 * pace_score +
        0.20 * (1.0 - min(pause_ratio / 0.5, 1.0))
    )
    clarity_score = round(clarity_raw * 10, 1)
    print(f"Clarity score components: speech_ratio_score={speech_ratio_score:.2f}, pace_score={pace_score:.2f}, pause_ratio_penalty={min(pause_ratio / 0.5, 1.0):.2f} → clarity_score={clarity_score:.1f}")
    # ── 8. Coaching notes ────────────────────────────────────────────────────
    notes = _build_notes(
        tone=tone,
        pitch_std=pitch_std,
        long_pauses=long_pauses,
        pause_ratio=pause_ratio,
        pace_wpm=pace_wpm,
        confidence_score=confidence_score,
        clarity_score=clarity_score,
    )
    print(f"Generated feedback notes: {notes}")
    return {
        "confidence_score": confidence_score,
        "clarity_score": clarity_score,
        "pace_wpm": pace_wpm,
        "hesitation_count": long_pauses,
        "pitch_variation": round(pitch_std, 2),
        "tone": tone,
        "speech_ratio": round(speech_ratio, 2),
        "duration_sec": round(duration_sec, 1),
        "feedback_notes": notes,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pace_score(wpm: int) -> float:
    """Returns 0–1 based on how close WPM is to the ideal range (120–160)."""
    if wpm == 0:
        return 0.5   # unknown — neutral
    if 120 <= wpm <= 160:
        return 1.0
    elif 100 <= wpm < 120 or 160 < wpm <= 180:
        return 0.75
    elif 80 <= wpm < 100 or 180 < wpm <= 200:
        return 0.5
    else:
        return 0.25


def _build_notes(
    tone, pitch_std, long_pauses, pause_ratio, pace_wpm,
    confidence_score, clarity_score
) -> list[str]:
    notes = []
    print(f"Building feedback notes based on analysis: tone={tone}, pitch_std={pitch_std:.2f}, long_pauses={long_pauses}, pause_ratio={pause_ratio:.2f}, pace_wpm={pace_wpm}, confidence_score={confidence_score:.1f}, clarity_score={clarity_score:.1f}")
    if tone == "flat":
        notes.append("Your voice was quite monotone — vary your pitch to sound more engaged and confident.")
    elif tone == "expressive":
        notes.append("Good vocal expressiveness — your pitch variation conveyed energy.")

    if long_pauses >= 4:
        notes.append(f"Detected {long_pauses} long pauses (>0.5s) — practice structuring your answer before speaking to reduce hesitation.")
    elif long_pauses >= 2:
        notes.append(f"A few noticeable hesitations ({long_pauses}) — minor pauses are fine, but try to keep momentum.")

    if pace_wpm > 0:
        if pace_wpm > 180:
            notes.append(f"You spoke quite fast ({pace_wpm} WPM) — slow down slightly to improve clarity.")
        elif pace_wpm < 90:
            notes.append(f"Your pace was slow ({pace_wpm} WPM) — a slightly faster cadence signals confidence.")
        else:
            notes.append(f"Good speaking pace ({pace_wpm} WPM).")

    if pause_ratio > 0.45:
        notes.append("More than 45% of your response was silence — try to fill pauses with structured thinking aloud.")

    if confidence_score >= 7.5:
        notes.append("Strong vocal confidence overall.")
    elif confidence_score < 5.0:
        notes.append("Low vocal confidence detected — project your voice more and reduce filler pauses.")

    return notes


def _fallback_result(reason: str) -> dict:
    print(f"Audio analysis fallback triggered: {reason}")
    return {
        "confidence_score": None,
        "clarity_score": None,
        "pace_wpm": 0,
        "hesitation_count": 0,
        "pitch_variation": 0.0,
        "tone": "unknown",
        "speech_ratio": 0.0,
        "duration_sec": 0.0,
        "feedback_notes": [f"Audio analysis unavailable: {reason}"],
    }