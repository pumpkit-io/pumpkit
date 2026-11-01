import { useCallback, useEffect, useId, useState, type ReactNode } from 'react';
import { ChevronDown, ShieldAlert, ShieldCheck } from 'lucide-react';
import { CopyRow } from '@/components/CopyRow';
import { ErrorBanner } from '@/components/ErrorBanner';
import { SettingsCard } from '@/components/SettingsCard';
import { showToast } from '@/components/Toaster';
import { Button } from '@/components/ui/button';
import { useInstance } from '@/features/instance/useInstance';
import { track } from '@/lib/analytics';
import { timeAgo } from '@/lib/relativeTime';
import { cn } from '@/lib/utils';
import { errorMessage } from '@/services/apiErrors';
import { appConnectionService, type AppConnection } from '@/services/appConnectionService';

const dayFormat = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' });
const dayAndYearFormat = new Intl.DateTimeFormat('en', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
});

function connectedDay(iso: string): string {
  const date = new Date(iso);
  const thisYear = date.getFullYear() === new Date().getFullYear();
  return (thisYear ? dayFormat : dayAndYearFormat).format(date);
}

function datesLabel(app: AppConnection): string {
  const used = app.lastUsedAt ? `last used ${timeAgo(app.lastUsedAt)}` : 'never used';
  return `Connected ${connectedDay(app.createdAt)} · ${used}`;
}

/** The name apps list the server under, as the backend's `claude mcp add` line names it. */
function serverName(appName: string): string {
  return (
    appName
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'pumpkit'
  );
}

function Steps({ children }: { children: ReactNode }) {
  return <p className="font-sans text-sm text-muted-foreground">{children}</p>;
}

function HowTo({ client, children }: { client: string; children: ReactNode }) {
  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-sm py-2 font-sans text-sm font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <ChevronDown
          aria-hidden
          className="h-4 w-4 shrink-0 -rotate-90 text-muted-foreground transition-transform group-open:rotate-0 motion-reduce:transition-none"
        />
        {client}
      </summary>
      <div className="space-y-3 pb-3 pl-6">{children}</div>
    </details>
  );
}

/** The MCP URL and how to add it to each app: what a User needs to connect one. */
function Setup({ mcpUrl, appName }: { mcpUrl: string | null; appName: string }) {
  if (mcpUrl === null) {
    return <ErrorBanner message="Couldn't load the URL to connect apps. Reload the page." />;
  }
  const name = serverName(appName);
  const json = (config: object) => JSON.stringify(config, null, 2);

  return (
    <div className="space-y-3">
      <CopyRow label="Paste this URL into your AI app" value={mcpUrl} copyLabel="Copy URL" />
      <div className="divide-y divide-border">
        <HowTo client="claude.ai, Claude Desktop, mobile">
          <Steps>
            In Claude, open Settings, then Connectors, and choose Add custom connector. Name it{' '}
            {appName}, paste the URL and leave the OAuth fields empty. Click Connect, sign in and
            click Allow. On Team and Enterprise plans an Owner adds it first; on Free you get one
            custom connector.
          </Steps>
        </HowTo>
        <HowTo client="ChatGPT">
          <Steps>
            In ChatGPT, open Settings, then Apps, then Advanced, and turn on Developer mode. Create
            an app with the URL as its MCP server URL and OAuth as its authentication, then sign in
            and click Allow. In a chat, pick {appName} from the + menu under Developer mode.
          </Steps>
        </HowTo>
        <HowTo client="Claude Code">
          <CopyRow
            label="Run this in a terminal"
            value={`claude mcp add --scope user --transport http ${name} ${mcpUrl}`}
            copyLabel="Copy the Claude Code command"
          />
          <Steps>Then, inside Claude Code, run /mcp, pick {name} and choose Authenticate.</Steps>
        </HowTo>
        <HowTo client="Codex CLI">
          <CopyRow
            label="Run these in a terminal, then sign in"
            value={`codex mcp add ${name} --url ${mcpUrl}\ncodex mcp login ${name}`}
            copyLabel="Copy the Codex commands"
          />
        </HowTo>
        <HowTo client="Gemini CLI">
          <CopyRow
            label="Add this to ~/.gemini/settings.json"
            value={json({ mcpServers: { [name]: { httpUrl: mcpUrl } } })}
            copyLabel="Copy the Gemini CLI settings"
          />
          <Steps>Then run /mcp auth {name} in Gemini CLI and sign in.</Steps>
        </HowTo>
        <HowTo client="Cursor">
          <CopyRow
            label="Add this to ~/.cursor/mcp.json"
            value={json({ mcpServers: { [name]: { url: mcpUrl } } })}
            copyLabel="Copy the Cursor settings"
          />
          <Steps>
            Then click Connect next to {name} in Cursor&apos;s MCP settings and sign in.
          </Steps>
        </HowTo>
        <HowTo client="VS Code">
          <CopyRow
            label="Add this to .vscode/mcp.json or your user mcp.json"
            value={json({ servers: { [name]: { type: 'http', url: mcpUrl } } })}
            copyLabel="Copy the VS Code settings"
          />
          <Steps>Then start the server and sign in when VS Code asks.</Steps>
        </HowTo>
      </div>
    </div>
  );
}

function AppRow({
  app,
  appName,
  onDisconnected,
}: {
  app: AppConnection;
  appName: string;
  onDisconnected: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const unverified = app.verifiedDomain === null;
  const Shield = unverified ? ShieldAlert : ShieldCheck;

  const disconnect = async () => {
    setDisconnecting(true);
    setError(null);
    try {
      await appConnectionService.disconnect(app.id);
      track('app_disconnected');
      showToast(`Disconnected ${app.appName}.`);
      onDisconnected();
    } catch (err) {
      setError(errorMessage(err, `Couldn't disconnect ${app.appName}. Try again.`));
      setDisconnecting(false);
    }
  };

  return (
    <li aria-label={app.appName} className="space-y-2 px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="truncate font-sans text-sm font-medium text-foreground">{app.appName}</p>
          <p
            className={cn(
              'flex items-center gap-1.5 font-sans text-xs',
              unverified ? 'text-warning' : 'text-foreground',
            )}
          >
            <Shield aria-hidden className="h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 break-words">
              {unverified ? 'Unverified' : `Verified: ${app.verifiedDomain}`}
            </span>
          </p>
          <p className="font-sans text-xs text-muted-foreground">{datesLabel(app)}</p>
        </div>
        {!confirming && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-10 shrink-0"
            aria-label={`Disconnect ${app.appName}`}
            onClick={() => setConfirming(true)}
          >
            Disconnect
          </Button>
        )}
      </div>
      {confirming && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="font-sans text-xs text-muted-foreground">
            {app.appName} stops working with {appName} at once.
          </p>
          <div className="flex shrink-0 gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-10"
              disabled={disconnecting}
              onClick={() => {
                setConfirming(false);
                setError(null);
              }}
            >
              Keep it
            </Button>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              className="h-10"
              disabled={disconnecting}
              onClick={() => void disconnect()}
            >
              {disconnecting ? 'Disconnecting…' : 'Disconnect app'}
            </Button>
          </div>
        </div>
      )}
      {error && <ErrorBanner message={error} />}
    </li>
  );
}

function LoadingList() {
  return (
    <div
      role="status"
      aria-label="Loading your connected apps"
      className="divide-y divide-border rounded-lg border border-border"
    >
      {[0, 1].map((row) => (
        <div key={row} className="space-y-2 px-4 py-3">
          <div className="h-4 w-1/3 animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
          <div className="h-3 w-1/2 animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
        </div>
      ))}
    </div>
  );
}

/** The Settings card for connecting AI apps over MCP and disconnecting the ones connected. */
export function ConnectedAppsCard() {
  const { mcp_url: mcpUrl, app_name: appName } = useInstance();
  const [apps, setApps] = useState<AppConnection[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [addingAnother, setAddingAnother] = useState(false);
  const setupId = useId();

  const load = useCallback(() => {
    let cancelled = false;
    setLoadFailed(false);
    setApps(null);
    appConnectionService
      .list()
      .then((listed) => !cancelled && setApps(listed))
      .catch(() => !cancelled && setLoadFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(load, [load]);

  const remove = (id: string) =>
    setApps((current) => (current ?? []).filter((app) => app.id !== id));

  let body: ReactNode;
  if (loadFailed) {
    body = <ErrorBanner message="Couldn't load your connected apps." onRetry={() => load()} />;
  } else if (apps === null) {
    body = <LoadingList />;
  } else if (apps.length === 0) {
    body = (
      <>
        <Setup mcpUrl={mcpUrl} appName={appName} />
        <p className="font-sans text-xs text-muted-foreground">No apps connected yet.</p>
      </>
    );
  } else {
    body = (
      <>
        <div className="space-y-2">
          <h3 className="font-sans text-sm font-medium text-foreground">Connected apps</h3>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {apps.map((app) => (
              <AppRow
                key={app.id}
                app={app}
                appName={appName}
                onDisconnected={() => remove(app.id)}
              />
            ))}
          </ul>
        </div>
        <div className="space-y-3">
          <button
            type="button"
            aria-expanded={addingAnother}
            aria-controls={setupId}
            onClick={() => setAddingAnother((open) => !open)}
            className="flex items-center gap-2 rounded-sm font-sans text-sm font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronDown
              aria-hidden
              className={cn(
                'h-4 w-4 text-muted-foreground transition-transform motion-reduce:transition-none',
                !addingAnother && '-rotate-90',
              )}
            />
            Add another app
          </button>
          {addingAnother && (
            <div id={setupId}>
              <Setup mcpUrl={mcpUrl} appName={appName} />
            </div>
          )}
        </div>
      </>
    );
  }

  return (
    <SettingsCard
      title="Connect AI apps"
      description={`Use ${appName} from Claude, ChatGPT, Cursor and other AI apps. Paste the URL into the app, then sign in and click Allow. There's no key to copy.`}
    >
      {body}
    </SettingsCard>
  );
}
