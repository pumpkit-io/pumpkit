export function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "250 generations and 50 X posts", leaving out a count with no cap; "" when both have none. */
export function generationsAndXPosts(generations: number | null, xPosts: number | null): string {
  return [
    generations !== null && count(generations, 'generation', 'generations'),
    xPosts !== null && count(xPosts, 'X post', 'X posts'),
  ]
    .filter((part): part is string => part !== false)
    .join(' and ');
}
