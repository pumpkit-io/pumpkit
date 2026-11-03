import type { VideoFacts } from '@/services/mediaService';

/** The largest side of the first frame sent as the video's preview, as the server's previews. */
const POSTER_MAX_SIDE = 1200;
/** A video the browser can't open within this long goes without a frame or length. */
const READ_TIMEOUT_MS = 15_000;

const NOTHING_READ: VideoFacts = { durationMs: null, poster: null };

function firstFrame(video: HTMLVideoElement): Promise<Blob | null> {
  const scale = Math.min(1, POSTER_MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  const context = canvas.getContext('2d');
  if (!context || !canvas.width || !canvas.height) return Promise.resolve(null);
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85));
}

/**
 * A video's length and first frame, read by the browser, which can decode what Pumpkit's
 * server never does. Whatever it can't read is null; it never rejects.
 */
export function readVideo(file: File): Promise<VideoFacts> {
  if (typeof URL.createObjectURL !== 'function') return Promise.resolve(NOTHING_READ);
  const url = URL.createObjectURL(file);
  const video = document.createElement('video');
  video.muted = true;
  video.playsInline = true;
  video.preload = 'auto';
  return new Promise<VideoFacts>((resolve) => {
    let durationMs: number | null = null;
    const done = (facts: VideoFacts) => {
      window.clearTimeout(timer);
      video.removeAttribute('src');
      video.load();
      URL.revokeObjectURL(url);
      resolve(facts);
    };
    const timer = window.setTimeout(() => done({ durationMs, poster: null }), READ_TIMEOUT_MS);
    video.onloadedmetadata = () => {
      durationMs = Number.isFinite(video.duration) ? Math.round(video.duration * 1000) : null;
    };
    video.onloadeddata = () => {
      firstFrame(video).then(
        (poster) => done({ durationMs, poster }),
        () => done({ durationMs, poster: null }),
      );
    };
    video.onerror = () => done({ durationMs, poster: null });
    video.src = url;
  });
}
