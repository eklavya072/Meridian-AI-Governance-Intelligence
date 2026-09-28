import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Epoch ms for a server timestamp. Stored times are UTC; one sent without an
// offset (rows from before the API added it) is parsed as UTC too, because a
// bare "2026-09-24T10:03:24" is read as the viewer's LOCAL time — in India that
// started a five-minute run's clock five and a half hours early.
export function parseServerTime(iso: string): number {
  return Date.parse(/(Z|[+-]\d\d:?\d\d)$/i.test(iso) ? iso : `${iso}Z`)
}
