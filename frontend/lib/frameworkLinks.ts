import type { Framework } from "@/lib/api";

interface ReferenceSegment {
  text: string;
  /** Set when this segment matches a Framework Library entry — link to it. */
  framework?: Framework;
}

/**
 * Lowercase keys a framework's name can be matched by inside a free-text
 * reference. Full name plus the two common shortenings the model emits:
 *   - "EU AI Act (Regulation (EU) 2024/1689)" -> "EU AI Act"
 *   - "NIST AI Risk Management Framework 1.0" -> "NIST AI Risk Management Framework"
 * Keys are distinctive multi-word phrases, so a reference like "EU AI Act
 * Accessibility Mandates" resolves to the library entry without risk of
 * matching inside an unrelated word.
 */
function matchKeys(name: string): string[] {
  const keys = new Set<string>([name.toLowerCase()]);
  const parenIdx = name.indexOf("(");
  if (parenIdx > 0) {
    keys.add(name.slice(0, parenIdx).trim().toLowerCase());
  }
  // "NIST SP 1270: Bias Management in AI" -> "nist sp 1270" — the model
  // often writes the subtitle in parentheses instead of after a colon.
  const colonIdx = name.indexOf(":");
  if (colonIdx > 0) {
    keys.add(name.slice(0, colonIdx).trim().toLowerCase());
  }
  const versionMatch = name.match(/^(.*?)\s+\d+(?:\.\d+)*$/);
  if (versionMatch && versionMatch[1].trim()) {
    keys.add(versionMatch[1].trim().toLowerCase());
  }
  return [...keys];
}

interface MatchSpan {
  start: number;
  end: number;
  framework: Framework;
}

/**
 * Resolve the free-text `international_standard_reference` into clickable
 * segments: each named source that matches a Framework Library entry becomes
 * a link; unmatched text stays plain — never a broken link.
 */
export function resolveFrameworkLinks(
  reference: string,
  frameworks: Framework[]
): ReferenceSegment[] {
  const text = reference?.trim() ?? "";
  if (!text) return [];
  const lower = text.toLowerCase();

  const candidates = frameworks
    .map((fw) => ({ fw, keys: matchKeys(fw.name) }))
    .filter(({ keys }) => keys.some((k) => lower.includes(k)));

  if (candidates.length === 0) return [{ text }];

  const spans: MatchSpan[] = [];
  for (const { fw, keys } of candidates) {
    for (const key of keys) {
      let idx = lower.indexOf(key);
      while (idx !== -1) {
        spans.push({ start: idx, end: idx + key.length, framework: fw });
        idx = lower.indexOf(key, idx + 1);
      }
    }
  }
  // Keep the longest span at each position; drop overlaps.
  spans.sort((a, b) => a.start - b.start || b.end - a.end);
  const kept: MatchSpan[] = [];
  for (const s of spans) {
    if (kept.length && s.start < kept[kept.length - 1].end) continue;
    kept.push(s);
  }

  const segments: ReferenceSegment[] = [];
  let cursor = 0;
  for (const s of kept) {
    if (s.start > cursor) segments.push({ text: text.slice(cursor, s.start) });
    segments.push({ text: text.slice(s.start, s.end), framework: s.framework });
    cursor = s.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor) });
  return segments;
}
