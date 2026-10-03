import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

const PUBLIC_PATHS = new Set<string>(['/']);

function setRobotsMeta(content: string) {
  let tag = document.querySelector<HTMLMetaElement>('meta[name="robots"]');
  if (!tag) {
    tag = document.createElement('meta');
    tag.setAttribute('name', 'robots');
    document.head.appendChild(tag);
  }
  tag.setAttribute('content', content);
}

export function RobotsMetaController() {
  const { pathname } = useLocation();

  useEffect(() => {
    const isPublic = PUBLIC_PATHS.has(pathname);
    setRobotsMeta(isPublic ? 'index,follow' : 'noindex,nofollow');
  }, [pathname]);

  return null;
}
