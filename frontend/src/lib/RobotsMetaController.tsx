import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

function setRobotsMeta(content: string) {
  let tag = document.querySelector<HTMLMetaElement>('meta[name="robots"]');
  if (!tag) {
    tag = document.createElement('meta');
    tag.setAttribute('name', 'robots');
    document.head.appendChild(tag);
  }
  tag.setAttribute('content', content);
}

/** Lets search engines index the given public paths and keeps every other page out. */
export function RobotsMetaController({ indexablePaths }: { indexablePaths: ReadonlySet<string> }) {
  const { pathname } = useLocation();

  useEffect(() => {
    setRobotsMeta(indexablePaths.has(pathname) ? 'index,follow' : 'noindex,nofollow');
  }, [pathname, indexablePaths]);

  return null;
}
