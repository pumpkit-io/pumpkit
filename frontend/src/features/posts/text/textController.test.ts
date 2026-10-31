import { beforeEach, describe, expect, it, vi } from 'vitest';
import { textOf, type PostDetail, type Version } from '@/services/postService';
import { TextController } from './textController';
import { TEXT_SAVE_PAUSE_MS, TEXT_SAVE_RETRY_MS } from './textSaver';
import { httpError, ManualClock, MemoryBackend, settled } from './testing';

function version(number: number, texts: string[], feedback: string | null = null): Version {
  return {
    id: `version_${number}`,
    number,
    feedback: number === 1 ? null : (feedback ?? 'punchier'),
    format: texts.length > 1 ? 'thread' : 'post',
    parts: texts.map((text) => ({ text, charCount: text.length, charLimit: 280 })),
    createdAt: `2026-10-10T0${number}:00:00Z`,
  };
}

function draft(versions: Version[]): PostDetail {
  return {
    id: 'post_01',
    brief: 'ship small things',
    versions,
    text: textOf(versions[versions.length - 1]!),
    status: 'draft',
    scheduledPost: null,
  };
}

const ONE = [version(1, ['the first text'])];
const TWO = [version(1, ['the first text']), version(2, ['the second text'])];

let clock: ManualClock;
let track: ReturnType<typeof vi.fn>;

beforeEach(() => {
  clock = new ManualClock();
  track = vi.fn();
});

/** A controller over a server holding `post`, for a Subscribed User. */
function open(post: PostDetail) {
  const server = new MemoryBackend(post);
  const controller = new TextController(post, { backend: server.port, clock, track });
  controller.setGate({ status: post.status });
  const texts = () => controller.snapshot().text?.parts.map((p) => p.text);
  return { server, controller, texts };
}

describe('TextController', () => {
  describe('editing', () => {
    it('shows an edit at once, marked edited, and saves it after a pause', async () => {
      const { server, controller, texts } = open(draft(ONE));

      controller.edit(['the first text, edited'], 'typing');

      expect(texts()).toEqual(['the first text, edited']);
      expect(controller.snapshot().text?.edited).toBe(true);
      expect(controller.snapshot().save).toEqual({ kind: 'pending' });
      expect(server.callsOf('saveText')).toEqual([]);
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      expect(server.callsOf('saveText')).toEqual([[['the first text, edited']]]);
      expect(server.textParts).toEqual(['the first text, edited']);
      expect(controller.snapshot().save).toEqual({ kind: 'saved' });
    });

    it('saves a burst of typing once, and tracks it once', async () => {
      const { server, controller } = open(draft(ONE));

      controller.edit(['the first text,'], 'typing');
      await clock.advance(TEXT_SAVE_PAUSE_MS / 2);
      controller.edit(['the first text, again'], 'typing');
      await clock.advance(TEXT_SAVE_PAUSE_MS);

      expect(server.callsOf('saveText')).toEqual([[['the first text, again']]]);
      expect(track.mock.calls.filter(([event]) => event === 'post_text_edited')).toEqual([
        ['post_text_edited', { format: 'post', part_count: 1 }],
      ]);
    });

    it('marks the Text unedited once typing brings it back to its Version', () => {
      const { controller } = open(draft(ONE));

      controller.edit(['the first text!'], 'typing');
      controller.edit(['the first text'], 'deleting');

      expect(controller.snapshot().text?.edited).toBe(false);
    });

    it("takes the server's answer to a save", async () => {
      const { server, controller } = open(draft(ONE));
      server.port.saveText = async (parts) => ({
        format: 'post',
        parts: parts.map((text) => ({ text, charCount: 99, charLimit: 280 })),
        versionNumber: 1,
        edited: true,
      });

      controller.edit(['counted by the server'], 'paste');
      await clock.advance(TEXT_SAVE_PAUSE_MS);

      expect(controller.snapshot().text?.parts[0]?.charCount).toBe(99);
    });

    it('drops the answer to a save the User has typed past', async () => {
      const { server, controller, texts } = open(draft(ONE));
      const save = server.hold('saveText');
      controller.edit(['first'], 'paste');
      await clock.advance(TEXT_SAVE_PAUSE_MS);

      controller.edit(['first, then more'], 'typing');
      await save.release();

      expect(texts()).toEqual(['first, then more']);
      expect(controller.snapshot().text?.edited).toBe(true);
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      expect(server.textParts).toEqual(['first, then more']);
    });

    it('drops the answer to a save when a restore started since', async () => {
      const { server, controller, texts } = open(draft(TWO));
      const save = server.hold('saveText');
      const counted = server.port.saveText;
      server.port.saveText = async (parts) => ({
        ...(await counted(parts)),
        parts: parts.map((text) => ({ text, charCount: 99, charLimit: 280 })),
      });
      controller.edit(['edited'], 'paste');
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      const restore = server.hold('restoreVersion');

      controller.restore(1);
      await save.release();

      expect(controller.snapshot().text?.parts[0]?.charCount).not.toBe(99);
      await restore.release();
      expect(texts()).toEqual(['the first text']);
      expect(controller.snapshot().textVersion?.number).toBe(1);
      expect(server.textParts).toEqual(['the first text']);
    });

    it('says an edit was not saved and retries it, waiting longer each time', async () => {
      const { server, controller } = open(draft(ONE));
      server.failNext('saveText', httpError(null), 2);

      controller.edit(['edited'], 'paste');
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      expect(controller.snapshot().save).toEqual({ kind: 'retrying' });
      await clock.advance(TEXT_SAVE_RETRY_MS);
      expect(server.callsOf('saveText')).toHaveLength(2);
      await clock.advance(TEXT_SAVE_RETRY_MS);
      expect(server.callsOf('saveText')).toHaveLength(2);
      await clock.advance(TEXT_SAVE_RETRY_MS);

      expect(server.callsOf('saveText')).toHaveLength(3);
      expect(controller.snapshot().save).toEqual({ kind: 'saved' });
      expect(server.textParts).toEqual(['edited']);
    });

    it('says why an edit was refused, without retrying it', async () => {
      const { server, controller } = open(draft(ONE));
      server.failNext('saveText', httpError(409, 'This Post is scheduled.'), 5);

      controller.edit(['edited'], 'paste');
      await clock.advance(TEXT_SAVE_PAUSE_MS + TEXT_SAVE_RETRY_MS * 4);

      expect(controller.snapshot().save).toEqual({
        kind: 'refused',
        message: 'This Post is scheduled.',
      });
      expect(server.callsOf('saveText')).toHaveLength(1);
    });

    it('settles a failed edit at once, without waiting for the retry', async () => {
      const { server, controller } = open(draft(ONE));
      server.failNext('saveText', httpError(null));
      controller.edit(['edited'], 'paste');
      await clock.advance(TEXT_SAVE_PAUSE_MS);

      const settledText = controller.settle();

      expect(await settledText).toBe(true);
      expect(server.callsOf('saveText')).toHaveLength(2);
    });

    it('settles false when the server refuses the edit', async () => {
      const { server, controller } = open(draft(ONE));
      server.failNext('saveText', httpError(422, 'Too long.'));
      controller.edit(['edited'], 'paste');

      expect(await controller.settle()).toBe(false);
    });

    it('sends the edit the pause still holds when disposed', async () => {
      const { server, controller } = open(draft(ONE));
      controller.edit(['edited'], 'paste');

      controller.dispose();
      await settled();

      expect(server.textParts).toEqual(['edited']);
    });

    it('sends the last edit once an earlier save lands, when disposed while it is out', async () => {
      const { server, controller } = open(draft(ONE));
      const save = server.hold('saveText');
      controller.edit(['first'], 'paste');
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      controller.edit(['first, then more'], 'typing');

      controller.dispose();
      await save.release();

      expect(server.callsOf('saveText')).toEqual([[['first']], [['first, then more']]]);
    });
  });

  describe('gate', () => {
    it('offers every tool on a Draft for a Subscribed User', () => {
      const { controller } = open(draft(ONE));

      expect(controller.snapshot().can).toEqual({
        edit: true,
        undo: false,
        redo: false,
        restore: true,
        sendFeedback: true,
        postTo: true,
      });
    });

    it('offers nothing once the Post is scheduled', async () => {
      const { server, controller } = open(draft(TWO));
      controller.edit(['edited'], 'paste');

      controller.setGate({ status: 'scheduled' });
      controller.undo();
      controller.restore(1);

      expect(Object.values(controller.snapshot().can)).not.toContain(true);
      expect(await controller.sendFeedback('shorter', 'post')).toBe('notSaved');
      expect(server.callsOf('restoreVersion')).toEqual([]);
      expect(server.callsOf('addVersion')).toEqual([]);
    });
  });

  describe('undo and redo', () => {
    it('undoes and redoes each burst of typing, saving the Text it lands on', async () => {
      const { server, controller, texts } = open(draft(ONE));
      controller.edit(['the first text,'], 'typing');
      controller.edit(['the first text, again'], 'typing');
      await clock.advance(1_000);
      controller.edit(['the first text, again!'], 'typing');

      controller.undo();
      expect(texts()).toEqual(['the first text, again']);
      controller.undo();

      expect(texts()).toEqual(['the first text']);
      expect(controller.snapshot().text?.edited).toBe(false);
      expect(controller.snapshot().can.undo).toBe(false);
      expect(controller.snapshot().announcement?.message).toBe('Undid: your edit');
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      expect(server.textParts).toEqual(['the first text']);

      controller.redo();
      expect(texts()).toEqual(['the first text, again']);
      expect(controller.snapshot().announcement?.message).toBe('Redid: your edit');
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      expect(server.textParts).toEqual(['the first text, again']);
      expect(track).toHaveBeenCalledWith('text_undone', { step: 'edit' });
      expect(track).toHaveBeenCalledWith('text_redone', { step: 'edit' });
    });

    it('highlights each step, under a new key each time, and drops it once the User types', () => {
      const { controller } = open(draft(ONE));
      controller.edit(['the first text, more'], 'paste');

      controller.undo();
      const undone = controller.snapshot().trace;
      controller.redo();
      const redone = controller.snapshot().trace;

      expect(undone).toMatchObject({
        before: ['the first text, more'],
        after: ['the first text'],
      });
      expect(redone).toMatchObject({ before: ['the first text'], after: ['the first text, more'] });
      expect(redone!.key).not.toBe(undone!.key);
      controller.edit(['the first text, more!'], 'typing');
      expect(controller.snapshot().trace).toBeNull();
    });

    it('undoes a rewrite in one step, restoring the Version the Feedback was given on', async () => {
      const { server, controller, texts } = open(draft(ONE));
      server.nextRewrite = ['the second text'];
      controller.edit(['my own edit'], 'paste');
      await controller.sendFeedback('Punchier hook', 'post');

      controller.undo();
      expect(texts()).toEqual(['my own edit']);
      expect(controller.snapshot().textVersion?.number).toBe(1);
      expect(controller.snapshot().announcement?.message).toBe('Undid: rewrite from feedback');
      await clock.advance(TEXT_SAVE_PAUSE_MS);

      expect(server.callsOf('restoreVersion')).toEqual([[1]]);
      expect(server.text).toMatchObject({ versionNumber: 1, edited: true });
      expect(server.textParts).toEqual(['my own edit']);
      expect(track).toHaveBeenCalledWith('version_restored', { source: 'undo' });

      const saves = server.callsOf('saveText').length;
      controller.redo();
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      expect(texts()).toEqual(['the second text']);
      expect(server.callsOf('restoreVersion')).toEqual([[1], [2]]);
      expect(server.callsOf('saveText')).toHaveLength(saves);
    });

    it('offers no undo, redo or restore while an undo across a rewrite is out', async () => {
      const { server, controller } = open(draft(TWO));
      controller.restore(1);
      await settled();
      const restore = server.hold('restoreVersion');

      controller.undo();
      await settled();

      expect(controller.snapshot()).toMatchObject({
        restoring: true,
        can: { undo: false, redo: false, restore: false, edit: true },
      });
      controller.redo();
      controller.restore(1);
      await restore.release();
      expect(server.callsOf('restoreVersion')).toEqual([[1], [2]]);
      expect(controller.snapshot().can.redo).toBe(true);
    });

    it('takes a refused undo across a rewrite back, typing during it included', async () => {
      const { server, controller, texts } = open(draft(ONE));
      server.nextRewrite = ['the second text'];
      await controller.sendFeedback('Punchier hook', 'post');
      const restore = server.hold('restoreVersion');
      controller.undo();

      controller.edit(['the first text, mine'], 'typing');
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      await restore.fail(httpError(503, 'Pumpkit is down for a moment.'));

      expect(texts()).toEqual(['the second text']);
      expect(controller.snapshot()).toMatchObject({
        textVersion: { number: 2 },
        restoreError: 'Pumpkit is down for a moment.',
        can: { undo: true, redo: false },
      });
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      expect(server.callsOf('saveText')).toEqual([]);
    });

    it("words a refused undo that gives no reason after what it couldn't do", async () => {
      const { server, controller } = open(draft(ONE));
      await controller.sendFeedback('Punchier hook', 'post');
      server.failNext('restoreVersion', httpError(null));

      controller.undo();
      await settled();

      expect(controller.snapshot().restoreError).toBe("Couldn't undo that change. Try again.");
    });

    it('saves typing done during an undo across a rewrite once it reaches the server', async () => {
      const { server, controller, texts } = open(draft(ONE));
      await controller.sendFeedback('Punchier hook', 'post');
      const restore = server.hold('restoreVersion');
      controller.undo();

      controller.edit(['the first text, mine'], 'typing');
      await clock.advance(TEXT_SAVE_PAUSE_MS);
      expect(server.callsOf('saveText')).toEqual([]);
      await restore.release();
      expect(texts()).toEqual(['the first text, mine']);
      await clock.advance(TEXT_SAVE_PAUSE_MS);

      expect(server.callsOf('saveText')).toEqual([[['the first text, mine']]]);
      expect(server.text).toMatchObject({ versionNumber: 1, edited: true });
    });

    it('undoes a restore in one step, without saving', async () => {
      const { server, controller, texts } = open(draft(TWO));
      controller.restore(1);
      await settled();

      controller.undo();
      await clock.advance(TEXT_SAVE_PAUSE_MS);

      expect(texts()).toEqual(['the second text']);
      expect(controller.snapshot().announcement?.message).toBe('Undid: restore of version 1');
      expect(server.callsOf('restoreVersion')).toEqual([[1], [2]]);
      expect(server.callsOf('saveText')).toEqual([]);
    });

    it('counts the rewrites typing drops from redo', async () => {
      const { controller } = open(draft(ONE));
      await controller.sendFeedback('Punchier hook', 'post');
      controller.undo();
      await settled();

      controller.edit(['the first text, mine'], 'typing');

      expect(controller.snapshot().droppedRewrites).toMatchObject({ count: 1 });
      expect(controller.snapshot().can.redo).toBe(false);
      expect(track).toHaveBeenCalledWith('redo_rewrites_dropped', { count: 1 });
    });
  });

  describe('restoring from History', () => {
    it('makes the Version the Text, announced and highlighted', async () => {
      const { server, controller, texts } = open(draft(TWO));

      controller.restore(1);
      expect(controller.snapshot().restoring).toBe(true);
      await settled();

      expect(texts()).toEqual(['the first text']);
      expect(controller.snapshot()).toMatchObject({
        restoring: false,
        textVersion: { number: 1 },
        text: { edited: false },
        announcement: { message: 'Restored version 1' },
        trace: { before: ['the second text'], after: ['the first text'] },
      });
      expect(server.text?.versionNumber).toBe(1);
      expect(track).toHaveBeenCalledWith('version_restored', { source: 'history' });
    });

    it('drops an edit not yet saved', async () => {
      const { server, controller, texts } = open(draft(TWO));
      controller.edit(['edited'], 'paste');

      controller.restore(1);
      await clock.advance(TEXT_SAVE_PAUSE_MS);

      expect(texts()).toEqual(['the first text']);
      expect(controller.snapshot().save).toEqual({ kind: 'saved' });
      expect(server.callsOf('saveText')).toEqual([]);
    });

    it('keeps the Text and says why when a restore is refused', async () => {
      const { server, controller, texts } = open(draft(TWO));
      server.failNext('restoreVersion', httpError(null));

      controller.restore(1);
      await settled();

      expect(texts()).toEqual(['the second text']);
      expect(controller.snapshot().restoreError).toBe("Couldn't restore version 1. Try again.");
      expect(track).not.toHaveBeenCalledWith('version_restored', expect.anything());
    });
  });

  describe('Feedback', () => {
    it('saves the edit first, then makes the next Version the Text', async () => {
      const { server, controller, texts } = open(draft(ONE));
      server.nextRewrite = ['the second text'];
      controller.edit(['edited'], 'paste');

      const sending = controller.sendFeedback('shorter', 'post');
      expect(controller.snapshot()).toMatchObject({
        writing: true,
        can: { edit: false, sendFeedback: false, postTo: false },
      });

      expect(await sending).toBe('sent');
      expect(server.calls.map((c) => c.method)).toEqual(['saveText', 'addVersion']);
      expect(server.callsOf('addVersion')).toEqual([['shorter', 'post', ['edited']]]);
      expect(texts()).toEqual(['the second text']);
      expect(controller.snapshot()).toMatchObject({
        writing: false,
        versions: [{ number: 1 }, { number: 2 }],
        textVersion: { number: 2 },
        trace: { before: ['edited'], after: ['the second text'] },
        can: { undo: true },
      });
      expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'feedback' });
    });

    it('sends only once a restore out has reached the server', async () => {
      const { server, controller } = open(draft(TWO));
      const restore = server.hold('restoreVersion');
      controller.restore(1);

      const sending = controller.sendFeedback('shorter', 'post');
      await settled();
      expect(server.callsOf('addVersion')).toEqual([]);
      await restore.release();

      expect(await sending).toBe('sent');
      expect(server.callsOf('addVersion')).toEqual([['shorter', 'post', ['the first text']]]);
    });

    it('sends nothing when the edit could not be saved', async () => {
      const { server, controller } = open(draft(ONE));
      server.failNext('saveText', httpError(422, 'Too long.'));
      controller.edit(['edited'], 'paste');

      expect(await controller.sendFeedback('shorter', 'post')).toBe('notSaved');
      expect(server.callsOf('addVersion')).toEqual([]);
      expect(controller.snapshot().writing).toBe(false);
    });

    it('hands a failure back, tracked unless the server refused it', async () => {
      const { server, controller, texts } = open(draft(ONE));
      const down = httpError(503);
      server.failNext('addVersion', down);
      server.failNext('addVersion', httpError(403));

      expect(await controller.sendFeedback('shorter', 'post')).toEqual({ failed: down });
      expect(track).toHaveBeenCalledWith('post_version_failed', { kind: 'feedback' });
      track.mockClear();
      expect(await controller.sendFeedback('shorter', 'post')).toEqual({
        failed: expect.anything(),
      });
      expect(track).not.toHaveBeenCalledWith('post_version_failed', expect.anything());
      expect(texts()).toEqual(['the first text']);
    });

    it('clears the last restore error', async () => {
      const { server, controller } = open(draft(TWO));
      server.failNext('restoreVersion', httpError(null));
      controller.restore(1);
      await settled();

      await controller.sendFeedback('shorter', 'post');

      expect(controller.snapshot().restoreError).toBeNull();
    });
  });

  describe('subscribers', () => {
    it('hears each change, with a new snapshot only when something changed', () => {
      const { controller } = open(draft(ONE));
      const heard = vi.fn();
      const unsubscribe = controller.subscribe(heard);
      const before = controller.snapshot();

      expect(controller.snapshot()).toBe(before);
      controller.edit(['edited'], 'paste');

      expect(heard).toHaveBeenCalled();
      expect(controller.snapshot()).not.toBe(before);
      unsubscribe();
      heard.mockClear();
      controller.edit(['edited again'], 'paste');
      expect(heard).not.toHaveBeenCalled();
    });
  });
});
