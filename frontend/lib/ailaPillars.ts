/**
 * Maps Meridian's eight governance dimensions onto UNDP's AI Landscape
 * Assessment (AILA) pillars, so a DAI Hub reader meets the output already
 * organised the way their own instrument is.
 *
 * AILA assesses three pillars: AI Ecosystem, AI for Government, and AI
 * Regulation & Ethics.
 *
 * Meridian populates two of them. Six of the eight dimensions are regulatory
 * and ethical questions, two are ecosystem questions, and NONE speak to AI for
 * Government — that pillar asks how the state adopts and uses AI internally,
 * which a policy document's text cannot evidence. The imbalance is stated
 * rather than smoothed over: it makes Meridian a deep instrument for one AILA
 * pillar, complementing an assessment rather than duplicating one, and a
 * reader should be able to see the boundary instead of discovering it.
 */

export const AILA_PILLARS = {
  ECOSYSTEM: "AI Ecosystem",
  GOVERNMENT: "AI for Government",
  REGULATION: "AI Regulation & Ethics",
} as const;

export type AilaPillar = (typeof AILA_PILLARS)[keyof typeof AILA_PILLARS];

const DIMENSION_PILLAR: Record<string, AilaPillar> = {
  Transparency: AILA_PILLARS.REGULATION,
  Accountability: AILA_PILLARS.REGULATION,
  Privacy: AILA_PILLARS.REGULATION,
  Safety: AILA_PILLARS.REGULATION,
  Fairness: AILA_PILLARS.REGULATION,
  "Human Autonomy": AILA_PILLARS.REGULATION,
  // Access, participation and the resource base an AI ecosystem runs on —
  // not rules imposed on deployers.
  Inclusivity: AILA_PILLARS.ECOSYSTEM,
  "Environmental Sustainability": AILA_PILLARS.ECOSYSTEM,
};

export function pillarFor(dimension: string): AilaPillar | undefined {
  return DIMENSION_PILLAR[dimension];
}
