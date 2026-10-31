export function formatAmount(cents: number, currency: string, locale?: string): string {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currency.toUpperCase(),
  }).format(cents / 100);
}

/** Like `formatAmount`, without the cents of a whole amount: "€10", but "€9.50". */
export function formatPrice(cents: number, currency: string, locale?: string): string {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currency.toUpperCase(),
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}
