export function formatRcaLabel(value?: string | null): string {
  if (!value) return '';
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase());
}
