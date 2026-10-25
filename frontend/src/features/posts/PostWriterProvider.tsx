import {
  createContext,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { FORMAT_POST, type Format } from '@/services/postService';
import { usePostWriter } from './usePostWriter';

type PostWriterValue = ReturnType<typeof usePostWriter> & {
  brief: string;
  setBrief: (brief: string) => void;
  /** The Format the Brief form starts the Post in. */
  format: Format;
  setFormat: (format: Format) => void;
  briefRef: RefObject<HTMLTextAreaElement>;
  /** Clears the Post and the Brief, back to a single post, then puts the cursor in the Brief box. */
  newPost: () => void;
};

export const PostWriterContext = createContext<PostWriterValue | null>(null);

/** One Post on screen for the writing area and the sidebar's New Post. */
export function PostWriterProvider({ children }: { children: ReactNode }) {
  const writer = usePostWriter();
  const { clear } = writer;
  const [brief, setBrief] = useState('');
  const [format, setFormat] = useState<Format>(FORMAT_POST);
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const [focusRequest, setFocusRequest] = useState(0);

  // The Brief box only mounts once the cleared Post has rendered away.
  useEffect(() => {
    if (focusRequest > 0) briefRef.current?.focus();
  }, [focusRequest]);

  const newPost = useCallback(() => {
    clear();
    setBrief('');
    setFormat(FORMAT_POST);
    setFocusRequest((n) => n + 1);
  }, [clear]);

  return (
    <PostWriterContext.Provider
      value={{ ...writer, brief, setBrief, format, setFormat, briefRef, newPost }}
    >
      {children}
    </PostWriterContext.Provider>
  );
}
