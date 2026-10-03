import { useRef, useState } from 'react';
import { Camera } from 'lucide-react';
import { processAvatarFile, AvatarProcessingError } from './imageProcessing';

interface AvatarEditorProps {
  value: string | null;
  initials: string;
  onChange: (next: string | null) => void;
  onError: (message: string | null) => void;
}

export function AvatarEditor({ value, initials, onChange, onError }: AvatarEditorProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);

  const openPicker = () => {
    if (busy) return;
    onError(null);
    inputRef.current?.click();
  };

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const dataUrl = await processAvatarFile(file);
      onChange(dataUrl);
    } catch (e) {
      const message =
        e instanceof AvatarProcessingError ? e.message : 'Could not process that image.';
      onError(message);
    } finally {
      setBusy(false);
      // Allow re-selecting the same file later.
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <div className="flex flex-col items-center gap-2">
      <button
        type="button"
        onClick={openPicker}
        aria-label="Change profile picture"
        className="group relative h-24 w-24 overflow-hidden rounded-full bg-primary-gradient-soft ring-1 ring-inset ring-primary/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        {value ? (
          <img
            src={value}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            draggable={false}
          />
        ) : (
          <span className="absolute inset-0 flex items-center justify-center bg-primary-gradient bg-clip-text text-2xl text-transparent">
            {initials}
          </span>
        )}
        <span
          aria-hidden
          className="absolute inset-0 flex items-center justify-center bg-foreground/45 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100"
        >
          <Camera className="h-5 w-5 text-background" />
        </span>
        {busy && (
          <span
            aria-hidden
            className="absolute inset-0 flex items-center justify-center bg-background/60 font-sans text-[11px] text-muted-foreground"
          >
            Processing…
          </span>
        )}
      </button>

      {value && !busy && (
        <button
          type="button"
          onClick={() => onChange(null)}
          className="font-sans text-[11px] text-muted-foreground underline-offset-2 hover:underline"
        >
          Remove photo
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
    </div>
  );
}
