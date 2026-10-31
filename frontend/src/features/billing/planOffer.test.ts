import { describe, expect, it } from 'vitest';
import { offerLines, trialLine } from './planOffer';

const ALLOWANCE = { generations: 500, xPosts: 100, linkXPosts: 10 };
const TRIAL = { days: 7, generations: 125, xPosts: 25, linkXPosts: 2 };

describe('offerLines', () => {
  it('lists the caps, the voice, scheduling, the AI tools and the Trial, in that order', () => {
    expect(offerLines(ALLOWANCE, TRIAL)).toEqual([
      { text: '500 post generations a month.', info: 'generations' },
      { text: 'Publish 100 X posts a month, up to 10 of them with a link.', info: 'xPosts' },
      { text: 'Write in the voice of your favorite X creators.' },
      { text: 'Schedule posts and threads to X.' },
      { text: 'Use it from Claude Code, Codex, Cursor or Gemini CLI.', info: 'aiTools' },
      { text: '7-day free trial: 125 generations and 25 X posts, up to 2 with a link.' },
    ]);
  });

  it('leaves out the lines of empty caps and the Trial when there is none', () => {
    expect(
      offerLines({ generations: null, xPosts: 100, linkXPosts: 0 }, null).map((l) => l.text),
    ).toEqual([
      'Publish 100 X posts a month, none with a link.',
      'Write in the voice of your favorite X creators.',
      'Schedule posts and threads to X.',
      'Use it from Claude Code, Codex, Cursor or Gemini CLI.',
    ]);
  });
});

describe('trialLine', () => {
  it("states the Trial's length and limits", () => {
    expect(trialLine(TRIAL)).toBe(
      '7-day free trial: 125 generations and 25 X posts, up to 2 with a link.',
    );
  });

  it('states only the length of a Trial with no caps', () => {
    expect(trialLine({ days: 7, generations: null, xPosts: null, linkXPosts: null })).toBe(
      '7-day free trial.',
    );
  });
});
