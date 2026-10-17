import numpy as np
import soundfile as sf
import os
import subprocess


def trim_silence_and_fit(audio, sr, target_sec, next_target_sec, i):
    window = next_target_sec - target_sec

    # 1. Trim excess internal silence (>0.25s) to natural speech pauses
    frame_len = int(0.02 * sr)  # 20ms frames
    frames = [audio[j : j + frame_len] for j in range(0, len(audio), frame_len)]
    is_silent = [np.sqrt(np.mean(f**2)) < 0.01 for f in frames]
    max_silent_frames = int(0.25 / 0.02)
    output_frames = []
    silent_count = 0
    for f, silent in zip(frames, is_silent):
        if silent:
            silent_count += 1
            if silent_count <= max_silent_frames:
                output_frames.append(f)
        else:
            silent_count = 0
            output_frames.append(f)
    trimmed = np.concatenate(output_frames) if output_frames else audio
    trimmed_dur = len(trimmed) / sr

    # 2. Check if subtle speedup is needed to avoid colliding with the next scene cue
    max_allowed = max(window - 0.25, 3.0)
    if trimmed_dur > max_allowed:
        speed = min(1.30, trimmed_dur / max_allowed)
        tmp_in = f"/tmp/gt_in_{i}.wav"
        tmp_out = f"/tmp/gt_out_{i}.wav"
        sf.write(tmp_in, trimmed, sr)
        subprocess.run(
            ["/opt/homebrew/bin/ffmpeg", "-y", "-i", tmp_in, "-filter:a", f"atempo={speed:.4f}", tmp_out],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        final_audio, _ = sf.read(tmp_out)
        if os.path.exists(tmp_in):
            os.remove(tmp_in)
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
    else:
        final_audio = trimmed
        speed = 1.0

    return final_audio, speed


def main():
    sample_rate = 24000
    m = None

    # Total duration of ghosttrace_demo.mp4 is 109.44 seconds
    video_duration = 109.44

    script_cues = [
        (
            1.5,
            "[excited] Welcome to (((GHOSTTRACE))): the first graph-native incident investigation and response platform built on (((FalkorDB))). The AI proposes, the graph disposes.",
        ),
        (
            12.5,
            "[stern] Traditional incident response fails because attackers exploit unmodeled cached credentials. GHOSTTRACE combines bitemporal graph calculus with Laya's non-autoregressive ModernBERT decision engine for instant triage.",
        ),
        (
            26.0,
            "[contemplative] In our interactive simulation, disabling Alice's user account fails to contain the attack. Her workstation still holds a cached CI-runner token with deploy access directly to the payments API.",
        ),
        (
            37.5,
            "[excited] With one click, we launch a durable five-agent swarm coordinating directly in FalkorDB with compare-and-swap leases.",
        ),
        (
            47.0,
            "[stern] The seven-step story walks through the live investigation. When the attacker plants a forged token-rotation log, Evidence Calculus Rule R2 rejects the claim. Then, our CEGAR optimizer computes the exact Price-of-Certainty Pareto curve.",
        ),
        (
            63.0,
            "[excited] Notice step seven: an independent, standard-library mathematical verifier formally validates the containment certificate out-of-process.",
        ),
        (
            73.0,
            "[contemplative] In the attack graph view, defenders explore live multi-hop paths, inspect source provenance, and scrub through bitemporal time sliders to eliminate hindsight bias.",
        ),
        (
            84.5,
            "[contemplative] Track three, the Bitemporal Company Brain, resolves organizational ownership and surfaces conflicting CMDB records across world time and knowledge time.",
        ),
        (
            96.0,
            "[excited] Finally, our Graph Copilot uses Laya System 1 inference for sub-second intent routing and prompt guardrails, backed by machine-grounded Cypher evidence.",
        ),
        (106.5, "[stern] (((GHOSTTRACE))): Proven containment. Zero guesswork."),
    ]

    os.makedirs("voice_clips", exist_ok=True)
    processed_clips = []
    current_sample = 0

    print("Processing and placing voiceover clips...")
    for i, (target_sec, text) in enumerate(script_cues, 1):
        clip_path = f"voice_clips/clip_{i:02d}.wav"
        if os.path.exists(clip_path):
            print(f"[{i}/{len(script_cues)}] Using existing clip: {clip_path}")
            raw_audio, sr = sf.read(clip_path)
            sample_rate = sr
        else:
            if m is None:
                print("Loading KittenTTS 2 model...")
                from kittenml import KittenTTS

                m = KittenTTS("KittenML/kitten-tts-2")
                sample_rate = m.sample_rate
                print(f"Model loaded! Sample rate: {sample_rate}")
            print(f"[{i}/{len(script_cues)}] Synthesizing clip {i}...")
            raw_audio = m.generate(text, voice="Claire")
            sf.write(clip_path, raw_audio, sample_rate)

        if raw_audio.ndim > 1:
            raw_audio = raw_audio[:, 0]
        raw_audio = raw_audio.astype(np.float32)

        next_target = script_cues[i][0] if i < len(script_cues) else video_duration + 3.0
        audio, speed = trim_silence_and_fit(raw_audio, sample_rate, target_sec, next_target, i)

        target_sample = int(target_sec * sample_rate)
        start_sample = max(target_sample, current_sample + int(0.15 * sample_rate))
        end_sample = start_sample + len(audio)
        current_sample = end_sample

        processed_clips.append((start_sample, end_sample, audio))
        print(
            f"  Placed clip {i:02d}: target={target_sec:5.1f}s -> {start_sample / sample_rate:6.2f}s to {end_sample / sample_rate:6.2f}s (dur={len(audio) / sample_rate:5.2f}s, speed={speed:.2f}x)"
        )

    total_samples = max(int(video_duration * sample_rate), current_sample + int(1.0 * sample_rate))
    timeline = np.zeros(total_samples, dtype=np.float32)

    for start_sample, end_sample, audio in processed_clips:
        timeline[start_sample:end_sample] += audio

    # Normalize audio slightly to prevent clipping and ensure crisp sound
    peak = np.max(np.abs(timeline))
    if peak > 0.95:
        timeline = timeline * (0.95 / peak)

    voiceover_wav = "ghosttrace_voiceover.wav"
    sf.write(voiceover_wav, timeline, sample_rate)
    audio_duration = len(timeline) / sample_rate
    print(f"\nMaster voiceover track saved: {voiceover_wav} ({audio_duration:.2f}s)")

    # Multiplex with video using ffmpeg
    input_video = "../ghosttrace_demo.mp4"
    output_video = "../ghosttrace_demo_with_voiceover.mp4"
    artifact_dirs = [
        "/Users/balaji/.gemini/antigravity-cli/brain/2cf27088-7468-461b-895a-5667d85edffb",
        "/Users/balaji/.gemini/antigravity-cli/brain/b5351b7b-b816-42cb-88b9-03ee49650cd9",
    ]

    if audio_duration > video_duration:
        pad_duration = audio_duration - video_duration + 0.5
        print(f"Extending final video frame by {pad_duration:.2f}s to perfectly hold punchline...")
        cmd = [
            "/opt/homebrew/bin/ffmpeg",
            "-y",
            "-i",
            input_video,
            "-i",
            voiceover_wav,
            "-filter_complex",
            f"[0:v]tpad=stop_mode=clone:stop_duration={pad_duration:.2f}[v]",
            "-map",
            "[v]",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            output_video,
        ]
    else:
        cmd = [
            "/opt/homebrew/bin/ffmpeg",
            "-y",
            "-i",
            input_video,
            "-i",
            voiceover_wav,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            output_video,
        ]

    print(f"Running ffmpeg mux: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"Output video created: {output_video}")

    for ad in artifact_dirs:
        if os.path.exists(ad):
            target_path = os.path.join(ad, "ghosttrace_demo_with_voiceover.mp4")
            subprocess.run(["cp", output_video, target_path], check=True)
            print(f"Copied to artifact directory: {target_path}")

    print("\n[SUCCESS] Voiceover generation and video multiplexing complete!")


if __name__ == "__main__":
    main()
