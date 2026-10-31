import { useEffect, useState, type FormEvent } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { SettingsCard } from '@/components/SettingsCard';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { apiKeyService, type ApiKey, type CreatedApiKey } from '@/services/apiKeyService';

const date = (iso: string) => new Date(iso).toLocaleDateString();

function datesLabel(key: ApiKey): string {
  const used = key.lastUsedAt ? `Last used ${date(key.lastUsedAt)}` : 'Never used';
  return `Created ${date(key.createdAt)} · ${used}`;
}

function CopyRow({ label, value, copyLabel }: { label: string; value: string; copyLabel: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  useEffect(() => {
    if (state !== 'copied') return;
    const timer = window.setTimeout(() => setState('idle'), 2000);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setState('copied');
    } catch {
      setState('failed');
    }
  };

  return (
    <div className="space-y-1.5">
      <span className="font-sans text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex items-start gap-2">
        <code className="min-w-0 flex-1 select-all break-all rounded-md bg-muted px-3 py-2 font-mono text-xs text-foreground">
          {value}
        </code>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-10 shrink-0"
          aria-label={copyLabel}
          onClick={() => void copy()}
        >
          {state === 'copied' ? 'Copied' : 'Copy'}
        </Button>
      </div>
      {state === 'failed' && (
        <p className="font-sans text-xs text-muted-foreground">
          Couldn&apos;t copy. Select the text and copy it yourself.
        </p>
      )}
    </div>
  );
}

function NewKeyReveal({ created, onDone }: { created: CreatedApiKey; onDone: () => void }) {
  return (
    <div className="space-y-3 rounded-lg border border-border bg-muted/40 p-4">
      <p className="font-sans text-sm font-medium text-foreground">
        Copy “{created.apiKey.name}” now. It won’t be shown again.
      </p>
      <CopyRow label="Key" value={created.secret} copyLabel="Copy key" />
      <CopyRow
        label="Run this once to add it to Claude Code"
        value={created.claudeCommand}
        copyLabel="Copy command"
      />
      <div className="flex justify-end">
        <Button type="button" size="sm" className="h-10" onClick={onDone}>
          Done
        </Button>
      </div>
    </div>
  );
}

function KeyRow({
  apiKey,
  revoking,
  onRevoke,
}: {
  apiKey: ApiKey;
  revoking: boolean;
  onRevoke: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const nameId = `api-key-name-${apiKey.id}`;

  return (
    <li aria-labelledby={nameId} className="space-y-2 px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <p id={nameId} className="truncate font-sans text-sm font-medium text-foreground">
            {apiKey.name}
          </p>
          <p className="font-sans text-xs text-muted-foreground">
            <span className="font-mono">{apiKey.prefix}…</span>
          </p>
          <p className="font-sans text-xs text-muted-foreground">{datesLabel(apiKey)}</p>
        </div>
        {!confirming && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-10 shrink-0"
            aria-label={`Revoke ${apiKey.name}`}
            onClick={() => setConfirming(true)}
          >
            Revoke
          </Button>
        )}
      </div>
      {confirming && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="font-sans text-xs text-muted-foreground">
            Programs using this key stop working at once.
          </p>
          <div className="flex shrink-0 gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-10"
              disabled={revoking}
              onClick={() => setConfirming(false)}
            >
              Keep it
            </Button>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              className="h-10"
              disabled={revoking}
              onClick={onRevoke}
            >
              {revoking ? 'Revoking…' : 'Revoke key'}
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

/** The Settings card for API keys: creating and revoking one apply at once. */
export function ApiKeysSection() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { refresh: refreshSubscribed } = useSubscribed();

  useEffect(() => {
    let cancelled = false;
    apiKeyService
      .list()
      .then((listed) => !cancelled && setKeys(listed))
      .catch(() => !cancelled && setLoadFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    const typed = name.trim();
    if (!typed) return;
    setCreating(true);
    setError(null);
    try {
      const next = await apiKeyService.create(typed);
      setCreated(next);
      setKeys((current) => [...(current ?? []), next.apiKey]);
      setName('');
    } catch (err) {
      if (errorStatus(err) === 403) refreshSubscribed();
      else setError(errorMessage(err, "Couldn't create the key. Try again."));
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (id: string) => {
    setRevokingId(id);
    setError(null);
    try {
      await apiKeyService.revoke(id);
      setKeys((current) => (current ?? []).filter((k) => k.id !== id));
      if (created?.apiKey.id === id) setCreated(null);
    } catch (err) {
      setError(errorMessage(err, "Couldn't revoke the key. Try again."));
    } finally {
      setRevokingId(null);
    }
  };

  return (
    <SettingsCard
      title="API keys"
      description="A key lets an MCP client like Claude Code, Codex and Cursor write, edit and schedule posts on your behalf. Creating or revoking a key takes effect immediately."
    >
      {created && <NewKeyReveal created={created} onDone={() => setCreated(null)} />}

      <form onSubmit={create} className="flex gap-2">
        <label htmlFor="api-key-name" className="sr-only">
          Key name
        </label>
        <Input
          id="api-key-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Pick a name, like macbook"
          maxLength={80}
          autoComplete="off"
          disabled={creating}
          className="min-w-0 flex-1"
        />
        <Button type="submit" disabled={creating || !name.trim()} className="shrink-0">
          {creating ? 'Creating…' : 'Create key'}
        </Button>
      </form>

      {error && <ErrorBanner message={error} />}

      {loadFailed ? (
        <ErrorBanner message="Couldn't load your API keys. Reload the page to try again." />
      ) : keys === null ? (
        <p role="status" className="font-sans text-xs text-muted-foreground">
          Loading your API keys…
        </p>
      ) : keys.length === 0 ? (
        <p className="font-sans text-xs text-muted-foreground">
          No API keys yet. Name one above to connect Claude Code.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {keys.map((k) => (
            <KeyRow
              key={k.id}
              apiKey={k}
              revoking={revokingId === k.id}
              onRevoke={() => void revoke(k.id)}
            />
          ))}
        </ul>
      )}
    </SettingsCard>
  );
}
