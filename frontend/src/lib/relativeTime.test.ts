import { describe, expect, it } from 'vitest';
import { dayAndTime, shortTimeAgo, timeAgo } from './relativeTime';

const NOW = new Date('2026-10-06T12:00:00Z');

describe('timeAgo', () => {
  it.each([
    ['2026-10-06T11:59:30Z', 'just now'],
    ['2026-10-06T11:55:00Z', '5 minutes ago'],
    ['2026-10-06T09:30:00Z', '2 hours ago'],
    ['2026-10-05T10:00:00Z', 'yesterday'],
    ['2026-09-20T12:00:00Z', '2 weeks ago'],
    ['2026-10-06T12:00:10Z', 'just now'],
  ])('reads %s as "%s"', (iso, expected) => {
    expect(timeAgo(iso, NOW)).toBe(expected);
  });
});

describe('shortTimeAgo', () => {
  it.each([
    ['2026-10-06T11:59:30Z', 'now'],
    ['2026-10-06T11:55:00Z', '5m ago'],
    ['2026-10-06T09:30:00Z', '2h ago'],
    ['2026-10-05T10:00:00Z', '1d ago'],
    ['2026-09-20T12:00:00Z', '2w ago'],
    ['2026-06-06T12:00:00Z', '4mo ago'],
    ['2026-10-06T12:00:10Z', 'now'],
  ])('reads %s as "%s"', (iso, expected) => {
    expect(shortTimeAgo(iso, NOW)).toBe(expected);
  });
});

describe('dayAndTime', () => {
  const now = new Date(2026, 9, 6, 16, 0);

  it.each([
    [new Date(2026, 9, 6, 23, 59), 'today at 11:59 PM'],
    [new Date(2026, 9, 7, 0, 0), 'tomorrow at 12:00 AM'],
    [new Date(2026, 9, 7, 15, 42), 'tomorrow at 3:42 PM'],
    [new Date(2026, 9, 9, 9, 5), 'Oct 9 at 9:05 AM'],
  ])('reads %s as "%s"', (date, expected) => {
    expect(dayAndTime(date, now)).toBe(expected);
  });
});
