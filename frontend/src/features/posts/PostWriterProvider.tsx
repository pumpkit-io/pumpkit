import {
  createContext,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { usePostWriter } from './usePostWriter';

type PostWriterValue = ReturnType<typeof usePostWriter> & {
  brief: string;
  setBrief: (brief: string) => void;
  briefRef: RefObject<HTMLTextAreaElement>;
  /** Clears the Post and the Brief, then puts the cursor in the empty Brief box. */
  newPost: () => void;
};

export const PostWriterContext = createContext<PostWriterValue | null>(null);

/** One Post on screen for the writing area and the sidebar's New Post. */
export function PostWriterProvider({ children }: { children: ReactNode }) {
  const writer = usePostWriter();
  const { clear } = writer;
  const [brief, setBrief] = useState('');
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const [focusRequest, setFocusRequest] = useState(0);

  // The Brief box only mounts once the cleared Post has rendered away.
  useEffect(() => {
    if (focusRequest > 0) briefRef.current?.focus();
  }, [focusRequest]);

  const newPost = useCallback(() => {
    clear();
    setBrief('');
    setFocusRequest((n) => n + 1);
  }, [clear]);

  return (
    <PostWriterContext.Provider value={{ ...writer, brief, setBrief, briefRef, newPost }}>
      {children}
    </PostWriterContext.Provider>
  );
}
