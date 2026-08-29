import { GovernanceGap } from "@/lib/api";

/**
 * Names every governance mechanism a dimension is expected to provide, and
 * shows how far the document actually carries each one.
 *
 * This replaces a bare "38 of 45 mechanisms" figure. That number was
 * unreadable on its own: nothing in the interface said what the 45 mechanisms
 * WERE, so the reader was asked to trust a denominator they could not inspect.
 * The mechanism names themselves are plain language — "consent", "grievance /
 * redress", "human-in-the-loop" — so simply showing them removes the problem
 * the aggregate created.
 *
 * Deliberately shows only what the document DOES provide. Listing the
 * unaddressed provisions here invited a reading the panel cannot answer —
 * "how is this Covered when three chips are hollow?" — because coverage is a
 * judgement about normative force, not a tally of provisions. The absent
 * mechanisms belong with the recommendations, where a missing provision is
 * an action rather than an apparent contradiction.
 */

// The normative-force ladder (backend src/evidence_strength.py). Collapsed to
// two visual states — five would be a legend to memorise, and the reader's
// question here is only ever "is this a duty or a promise?".
const FORCE_STATES = {
  binding: {
    label: "Binding duty",
    dot: "bg-navy-950",
    chip: "border-navy-950 bg-navy-950/[0.06] text-navy-950",
  },
  // Darker than the original (/40 dot, /25 border) so it reads as a real
  // second state rather than disabled text, but pulled back from binding
  // enough that the two are never mistaken for each other at a glance — the
  // gap is the signal here, not just the darkness of either end.
  stated: {
    label: "Stated commitment",
    dot: "bg-navy-950/55",
    chip: "border-navy-950/38 bg-navy-950/[0.02] text-navy-950/78",
  },
} as const;

type ForceState = keyof typeof FORCE_STATES;

/** Tier 3 (Obligatory) and 4 (Enforceable) are duties; 0-2 are not. */
function stateForTier(tier: number): ForceState {
  return tier >= 3 ? "binding" : "stated";
}

function Chip({ name, state }: { name: string; state: ForceState }) {
  const s = FORCE_STATES[state];
  return (
    <span
      title={s.label}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] leading-none ${s.chip}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${s.dot}`} />
      {name}
    </span>
  );
}

export function ProvisionChecklist({ gap }: { gap: GovernanceGap }) {
  const present = gap.mechanisms_present || {};
  const entries = Object.entries(present);

  // Analyses stored before mechanism capture have no such field. Render
  // nothing rather than an empty panel implying the document provides none.
  if (entries.length === 0) return null;

  // Duties first, so the strongest ground reads without hunting.
  const ordered: Array<[string, ForceState]> = entries
    .slice()
    .sort((a, b) => b[1] - a[1])
    .map(([name, tier]) => [name, stateForTier(tier)] as [string, ForceState]);

  return (
    <div>
      <p className="module-heading mb-3">What the document provides</p>

      <div className="flex flex-wrap gap-1.5">
        {ordered.map(([name, state]) => (
          <Chip key={name} name={name} state={state} />
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {(Object.keys(FORCE_STATES) as ForceState[]).map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5 text-[11px] text-gray-500">
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${FORCE_STATES[k].dot}`} />
            {FORCE_STATES[k].label}
          </span>
        ))}
      </div>
    </div>
  );
}

export default ProvisionChecklist;
