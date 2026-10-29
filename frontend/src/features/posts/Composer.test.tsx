import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Format } from '@/services/postService';
import { Composer, type ComposerProps } from './Composer';

function renderComposer(props: Partial<ComposerProps> = {}) {
  const onSend = vi.fn();
  render(
    <Composer
      label="Feedback"
      placeholder="What should change?"
      value="Shorter"
      onChange={() => {}}
      format={'post' as Format}
      onFormatChange={() => {}}
      maxLength={100}
      sendLabel="Send Feedback"
      shortcutVerb="send"
      onSend={onSend}
      {...props}
    />,
  );
  return { onSend };
}

describe('Composer', () => {
  it('shows the trailing action after the send arrow', () => {
    renderComposer({ trailingAction: <button type="button">Post to…</button> });

    const send = screen.getByRole('button', { name: 'Send Feedback' });
    const postTo = screen.getByRole('button', { name: 'Post to…' });
    expect(send.compareDocumentPosition(postTo) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('puts the gate in place of the send arrow and keeps the trailing action', () => {
    const { onSend } = renderComposer({
      gate: <a href="/settings">Subscribe to write</a>,
      trailingAction: <button type="button">Post to…</button>,
    });

    expect(screen.queryByRole('button', { name: 'Send Feedback' })).not.toBeInTheDocument();
    expect(screen.queryByText(/↵ to send/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Subscribe to write' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Post to…' })).toBeInTheDocument();

    fireEvent.keyDown(screen.getByLabelText('Feedback'), { key: 'Enter', metaKey: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it('sends the typed text with the shortcut named by its verb', () => {
    const { onSend } = renderComposer();

    expect(screen.getByText(/↵ to send/)).toBeVisible();
    fireEvent.keyDown(screen.getByLabelText('Feedback'), { key: 'Enter', ctrlKey: true });

    expect(onSend).toHaveBeenCalledTimes(1);
  });
});
