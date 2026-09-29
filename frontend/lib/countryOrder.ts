import type { Workspace } from "@/lib/api";

/** The order the country workspaces are listed in, top to bottom. A country
 *  not named here (a visitor's own workspace) follows these, oldest first. */
const COUNTRY_ORDER = [
  "Egypt",
  "Kenya",
  "Rwanda",
  "India",
  "Japan",
  "China",
  "United Kingdom",
  "European Union",
];

function rank(country: string): number {
  const i = COUNTRY_ORDER.indexOf(country.trim());
  return i === -1 ? COUNTRY_ORDER.length : i;
}

export function byCountryOrder(a: Workspace, b: Workspace): number {
  return rank(a.country) - rank(b.country) || a.created_at.localeCompare(b.created_at);
}
