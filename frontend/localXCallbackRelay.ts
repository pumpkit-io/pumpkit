import type { IncomingMessage, ServerResponse } from 'node:http';

type Relay = (req: IncomingMessage, res: ServerResponse, next: () => void) => void;

export function createXCallbackRelay(publicURL: string): Relay {
  const port = /^http:\/\/localhost:([1-9][0-9]{0,4})$/.exec(publicURL)?.[1];
  if (!port || Number(port) > 65535)
    throw new Error('X callback relay requires http://localhost:PORT');
  const origin = new URL(publicURL);
  const callbackHost = new URL(`http://127.0.0.1:${port}`).host;
  return (req, res, next) => {
    res.setHeader('X-Pumpkit-Dev-Mode', 'personal');
    const url = new URL(req.url ?? '/', origin);
    if (
      req.method !== 'GET' ||
      req.headers.host !== callbackHost ||
      url.pathname !== '/oauth/x/callback'
    ) {
      next();
      return;
    }
    const destination = new URL('/oauth/x/callback', origin);
    url.searchParams.forEach((value, key) => {
      if (key === 'code' || key === 'state' || key === 'error')
        destination.searchParams.append(key, value);
    });
    res.writeHead(302, {
      Location: destination.href,
      'Cache-Control': 'no-store',
      'Referrer-Policy': 'no-referrer',
    });
    res.end();
  };
}
