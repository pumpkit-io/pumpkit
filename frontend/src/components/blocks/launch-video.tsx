import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import * as SliderPrimitive from '@radix-ui/react-slider';
import { Maximize, Minimize, Pause, Play, RotateCcw, Volume2, VolumeX } from 'lucide-react';
import launchVideoMp4 from '@/assets/launch-video/launch-video.mp4';
import launchVideoWebm from '@/assets/launch-video/launch-video.webm';
import launchVideoPoster from '@/assets/launch-video/launch-video-poster.jpg';
import { track } from '@/lib/analytics';
import { REDUCED_MOTION, useMediaQuery } from '@/lib/useMediaQuery';
import { cn } from '@/lib/utils';

/** Tailwind's `lg`, where the hero turns two-column. */
const DESKTOP = '(min-width: 1024px)';

type WebkitVideo = HTMLVideoElement & { webkitEnterFullscreen?: () => void };

function formatTime(seconds: number): string {
  const whole = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

/**
 * The launch video with custom controls. It starts muted and autoplays only while in view on a
 * desktop-sized viewport without reduced motion; elsewhere it waits on its poster for a play.
 */
export function LaunchVideo() {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [started, setStarted] = useState(false);
  const [ended, setEnded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [muted, setMuted] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);

  const desktop = useMediaQuery(DESKTOP);
  const reducedMotion = useMediaQuery(REDUCED_MOTION);
  const canAutoplay = desktop && !reducedMotion;
  const startedRef = useRef(false);
  const playingRef = useRef(false);
  const pausedByScrollRef = useRef(false);
  const nextPlayTriggerRef = useRef<'autoplay' | 'visitor'>('visitor');

  useEffect(() => {
    if (videoRef.current) videoRef.current.muted = muted;
  }, [muted]);

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  useEffect(() => {
    const node = rootRef.current;
    const video = videoRef.current;
    if (!node || !video) return;

    const onEnter = () => {
      if (pausedByScrollRef.current || (canAutoplay && !startedRef.current)) {
        pausedByScrollRef.current = false;
        nextPlayTriggerRef.current = startedRef.current ? 'visitor' : 'autoplay';
        video.play()?.catch(() => {});
      }
    };
    const onLeave = () => {
      if (!playingRef.current) return;
      pausedByScrollRef.current = true;
      video.pause();
    };

    if (typeof IntersectionObserver === 'undefined') {
      onEnter();
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => (entry.isIntersecting ? onEnter() : onLeave()),
      { threshold: 0.5 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [canAutoplay]);

  const play = () => {
    const video = videoRef.current;
    if (!video) return;
    nextPlayTriggerRef.current = 'visitor';
    pausedByScrollRef.current = false;
    if (ended) video.currentTime = 0;
    video.play()?.catch(() => {});
  };

  const togglePlay = () => {
    if (playing) {
      pausedByScrollRef.current = false;
      videoRef.current?.pause();
    } else {
      play();
    }
  };

  const watchAgain = () => {
    track('landing_video_watched_again');
    play();
  };

  const toggleSound = () => {
    if (muted) track('landing_video_sound_turned_on');
    setMuted(!muted);
  };

  const seek = (seconds: number) => {
    if (videoRef.current) videoRef.current.currentTime = seconds;
    setCurrentTime(seconds);
    if (ended && seconds < duration) setEnded(false);
  };

  const toggleFullscreen = () => {
    const root = rootRef.current;
    const video = videoRef.current as WebkitVideo | null;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else if (root?.requestFullscreen) {
      void root.requestFullscreen();
    } else {
      // iOS Safari only lets the video element itself go fullscreen.
      video?.webkitEnterFullscreen?.();
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const isButton = target.tagName === 'BUTTON';
    if (event.key === 'k' || event.key === 'K' || (event.key === ' ' && !isButton)) {
      event.preventDefault();
      togglePlay();
    }
  };

  const controlsPinned = !playing;
  const timeLabel = `${formatTime(currentTime)} / ${formatTime(duration)}`;

  return (
    <div
      ref={rootRef}
      role="group"
      aria-label="Launch video"
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="group/video relative size-full bg-black outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <video
        ref={videoRef}
        className="size-full object-contain"
        poster={launchVideoPoster}
        preload="metadata"
        playsInline
        muted
        onClick={failed ? undefined : togglePlay}
        onPlay={() => {
          if (!startedRef.current) {
            track('landing_video_played', { trigger: nextPlayTriggerRef.current });
          }
          startedRef.current = true;
          playingRef.current = true;
          setStarted(true);
          setPlaying(true);
          setEnded(false);
        }}
        onPause={() => {
          playingRef.current = false;
          setPlaying(false);
        }}
        onEnded={() => {
          playingRef.current = false;
          setPlaying(false);
          setEnded(true);
        }}
        onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
        onDurationChange={(event) => setDuration(event.currentTarget.duration)}
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onError={() => setFailed(true)}
      >
        <source src={launchVideoWebm} type="video/webm" />
        {/* A failed source fires its error on the source element, not on the video. */}
        <source src={launchVideoMp4} type="video/mp4" onError={() => setFailed(true)} />
      </video>

      {failed ? (
        <div className="absolute inset-0">
          <img src={launchVideoPoster} alt="" className="size-full object-contain" />
          <p className="absolute inset-x-0 bottom-4 mx-auto w-fit rounded-full bg-black/75 px-4 py-2 text-sm text-white">
            The video couldn't load.
          </p>
        </div>
      ) : (
        <>
          {!started && !playing && (
            <CentreButton label="Play video" onClick={play}>
              <Play className="size-7 translate-x-0.5 fill-current" aria-hidden />
            </CentreButton>
          )}
          {ended && (
            <CentreButton label="Watch again" onClick={watchAgain} withText>
              <RotateCcw className="size-5" aria-hidden />
            </CentreButton>
          )}

          <button
            type="button"
            onClick={toggleSound}
            aria-label={muted ? 'Sound on' : 'Sound off'}
            className={cn(
              'absolute bottom-14 right-3 z-10 flex items-center gap-2 rounded-full bg-black/70 px-3 py-2 text-sm font-medium text-white backdrop-blur transition-opacity hover:bg-black/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white',
              !muted &&
                !controlsPinned &&
                'opacity-0 group-hover/video:opacity-100 group-focus-within/video:opacity-100',
            )}
          >
            {muted ? (
              <>
                <VolumeX className="size-4" aria-hidden />
                <span aria-hidden>Sound on</span>
              </>
            ) : (
              <Volume2 className="size-4" aria-hidden />
            )}
          </button>

          <div
            className={cn(
              'absolute inset-x-0 bottom-0 flex items-center gap-3 bg-gradient-to-t from-black/80 to-transparent px-3 pb-2.5 pt-8 text-white transition-opacity',
              !controlsPinned &&
                'opacity-0 group-hover/video:opacity-100 group-focus-within/video:opacity-100',
            )}
          >
            <BarButton label={playing ? 'Pause' : 'Play'} onClick={togglePlay}>
              {playing ? (
                <Pause className="size-4 fill-current" aria-hidden />
              ) : (
                <Play className="size-4 fill-current" aria-hidden />
              )}
            </BarButton>

            <SliderPrimitive.Root
              className="relative flex h-6 min-w-0 flex-1 touch-none select-none items-center"
              min={0}
              max={duration > 0 ? duration : 1}
              step={1}
              value={[Math.min(currentTime, duration || 0)]}
              disabled={duration <= 0}
              onValueChange={([value]) => seek(value)}
              onValueCommit={() => track('landing_video_scrubbed')}
            >
              <SliderPrimitive.Track className="relative h-1 w-full grow overflow-hidden rounded-full bg-white/35">
                <SliderPrimitive.Range className="absolute h-full bg-white" />
              </SliderPrimitive.Track>
              <SliderPrimitive.Thumb
                aria-label="Seek"
                aria-valuetext={`${formatTime(currentTime)} of ${formatTime(duration)}`}
                className="block size-3.5 rounded-full bg-white shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-black"
              />
            </SliderPrimitive.Root>

            <span className="shrink-0 text-xs tabular-nums">{timeLabel}</span>

            <BarButton
              label={fullscreen ? 'Exit full screen' : 'Full screen'}
              onClick={toggleFullscreen}
            >
              {fullscreen ? (
                <Minimize className="size-4" aria-hidden />
              ) : (
                <Maximize className="size-4" aria-hidden />
              )}
            </BarButton>
          </div>
        </>
      )}
    </div>
  );
}

function BarButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="flex size-8 shrink-0 items-center justify-center rounded-full hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
    >
      {children}
    </button>
  );
}

function CentreButton({
  label,
  onClick,
  withText = false,
  children,
}: {
  label: string;
  onClick: () => void;
  withText?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/30">
      <button
        type="button"
        onClick={onClick}
        aria-label={withText ? undefined : label}
        className={cn(
          'pointer-events-auto flex items-center justify-center gap-2 rounded-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-black',
          withText ? 'px-5 py-3 text-base font-medium' : 'size-16',
        )}
      >
        {children}
        {withText && label}
      </button>
    </div>
  );
}
