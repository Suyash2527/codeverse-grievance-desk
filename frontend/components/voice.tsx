"use client";

/**
 * Voice capture for the citizen desk.
 *
 * Records with MediaRecorder and posts the audio to the backend, which calls
 * the transcription model. The transcript is then sent as an ordinary chat
 * turn, so voice and typing converge on the same intake path and the citizen
 * still confirms a draft before anything is filed.
 *
 * The button is disabled, with a reason, when transcription is unavailable.
 * A recording that silently produced nothing would be worse than no button.
 */
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";

type Props = {
  language: string;
  available: boolean;
  label: string;
  listeningLabel: string;
  onTranscript: (text: string) => void;
  onError: (message: string) => void;
};

export function VoiceButton({
  language,
  available,
  label,
  listeningLabel,
  onTranscript,
  onError,
}: Props) {
  const [recording, setRecording] = useState(false);
  const [working, setWorking] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    return () => {
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        if (blob.size === 0) {
          onError("No audio was captured. Please try again.");
          return;
        }
        setWorking(true);
        try {
          const result = await api.transcribe(blob, language);
          if (result.text.trim()) {
            onTranscript(result.text);
          } else {
            onError("Nothing could be transcribed from that recording.");
          }
        } catch (err) {
          onError(
            err instanceof Error ? err.message : "transcription was unavailable",
          );
        } finally {
          setWorking(false);
        }
      };

      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch {
      onError(
        "The microphone is unavailable. Please allow access, or type instead.",
      );
    }
  }

  function stop() {
    recorderRef.current?.stop();
    setRecording(false);
  }

  const disabled = !available || working;

  return (
    <button
      type="button"
      onClick={() => (recording ? stop() : void start())}
      disabled={disabled}
      aria-pressed={recording}
      title={
        available
          ? label
          : "Speech-to-text needs OPENAI_API_KEY to be configured on the server."
      }
      className={`pressable shrink-0 px-4 py-3 rounded-card border text-[14px] ${
        recording
          ? "border-ink text-rose bg-rose-tint"
          : "border-line-strong text-ink-2 hover:text-ink"
      } disabled:opacity-40 disabled:cursor-not-allowed`}
    >
      <span className="flex items-center gap-2">
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            recording ? "bg-ink animate-pulse" : "bg-ink-3"
          }`}
          aria-hidden
        />
        {working ? "…" : recording ? listeningLabel : label}
      </span>
    </button>
  );
}
