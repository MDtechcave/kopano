export const money = (value?: number | null) => value == null ? '—' : new Intl.NumberFormat('en-ZA', { style: 'currency', currency: 'ZAR' }).format(value);
export const date = (value?: string | null) => value ? new Intl.DateTimeFormat('en-ZA', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value)) : '—';
export const titleCase = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());
export const initials = (name: string) => name.split(/\s+/).slice(0, 2).map((x) => x[0]).join('').toUpperCase();
