const GMAIL_DOMAINS = ["gmail.com", "googlemail.com"];

export function isGmailAddress(email: string): boolean {
  const atIndex = email.lastIndexOf("@");
  if (atIndex === -1 || atIndex === email.length - 1) return false;
  const domain = email.slice(atIndex + 1).toLowerCase();
  return GMAIL_DOMAINS.includes(domain);
}
