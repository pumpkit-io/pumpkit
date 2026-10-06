/** Characters as the backend counts them (code points), so an emoji is one, not two. */
export const charCount = (text: string) => [...text].length;

export const formatCount = (n: number) => n.toLocaleString('en-US');
