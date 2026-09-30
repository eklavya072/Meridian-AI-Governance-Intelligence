import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Epoch ms for a server timestamp. Stored times are UTC; one sent without an
// offset (older rows) is parsed as UTC too, because a bare ISO string would
// otherwise be read as the viewer's LOCAL time.
export function parseServerTime(iso: string): number {
  return Date.parse(/(Z|[+-]\d\d:?\d\d)$/i.test(iso) ? iso : `${iso}Z`)
}
