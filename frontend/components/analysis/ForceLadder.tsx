"use client";

/* The force ladder, in the product. The landing sells one idea, "we grade
   force, not vocabulary", on a five-rung ladder from a stated aspiration
   (T0) to an enforceable duty (T4); the analysis opened on a donut and a
   gauge that never showed it. This panel is that ladder, per dimension:
   for each mechanism the document establishes, the rung its strongest
   provision reaches. Brass marks the two rungs that bind (T3, T4), the
   same accent the hero gives its top rung. Read from the stored
   mechanisms_present, so every existing run can show it. */

import { motion } from "motion/react";
import type { GovernanceGap } from "@/lib/api";
import { EASE } from "@/lib/motion";

const RUNGS = [
  { tier: 0, name: "Aspirational" },
  { tier: 1, name: "Intentional" },
  { tier: 2, name: "Assigned" },
  { tier: 3, name: "Obligatory" },
  { tier: 4, name: "Enforceable" },
] as const;

/* Grey steps up the non-binding rungs with dark figures, brass on the
   binding ones with white figures (4.9:1 and 7.1:1). The count is the
   figure; the fill says only which rung. */
const RUNG_FILL = ["#EDEDED", "#DEDEDE", "#C4C4C4", "#8A6D1F", "#6C5513"];

export function ForceLadder({ gaps }: { gaps: GovernanceGap[] }) {
  const rows = gaps
    .filter((g) => !g.analysis_error)
    .map((g) => {
      const counts = [0, 0, 0, 0, 0];
      for (const tier of Object.values(g.mechanisms_present || {})) {
        const t = Math.max(0, Math.min(4, Math.round(Number(tier) || 0)));
        counts[t] += 1;
      }
      const top = counts.reduce((best, n, t) => (n > 0 ? t : best), -1);
      return {
        dimension: g.dimension,
        counts,
        absent: (g.mechanisms_absent || []).length,
        top,
      };
    });
  if (rows.every((r) => r.counts.every((n) => n === 0))) return null;

  return (
    <div className="rounded-xl border border-[color:var(--border)] bg-white p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-base font-bold text-grey-950">Force ladder</h3>
        <p className="text-xs text-grey-700">
          Mechanisms by the rung their strongest provision reaches.{" "}
          <span className="font-semibold text-brass">T3 and T4 bind.</span>
        </p>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[520px] border-separate border-spacing-x-1 border-spacing-y-1 text-left">
          <caption className="sr-only">
            For each dimension, how many of its mechanisms reach each rung of the
            normative-force ladder, from T0 aspirational to T4 enforceable.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="w-[30%] pb-1 text-[11px] font-semibold text-grey-700">
                Dimension
              </th>
              {RUNGS.map((r) => (
                <th
                  key={r.tier}
                  scope="col"
                  className={`pb-1 text-center text-[11px] font-semibold ${
                    r.tier >= 3 ? "text-brass" : "text-grey-700"
                  }`}
                >
                  <span className="block tabular-nums">T{r.tier}</span>
                  <span className="block font-medium">{r.name}</span>
                </th>
              ))}
              <th scope="col" className="pb-1 text-center text-[11px] font-semibold text-grey-700">
                Absent
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={row.dimension} className="group">
                <th
                  scope="row"
                  className="rounded-l-md py-1 pr-2 text-[13px] font-semibold text-grey-950 transition-colors group-hover:bg-grey-50"
                >
                  {row.dimension}
                </th>
                {row.counts.map((n, t) => (
                  <td key={t} className="p-0">
                    <motion.div
                      initial={{ opacity: 0, scaleX: 0.4 }}
                      whileInView={{ opacity: 1, scaleX: 1 }}
                      viewport={{ once: true, margin: "0px 0px -10% 0px" }}
                      transition={{ duration: 0.45, ease: EASE.out, delay: ri * 0.035 + t * 0.06 }}
                      className="flex h-8 origin-left items-center justify-center rounded-md text-[13px] font-bold tabular-nums"
                      style={
                        n > 0
                          ? { background: RUNG_FILL[t], color: t >= 3 ? "#FFFFFF" : "#0A0A0A" }
                          : { background: "rgba(10,10,10,0.035)", color: "#8A8A8A" }
                      }
                      title={`${row.dimension}: ${n} mechanism${n === 1 ? "" : "s"} at T${t} ${RUNGS[t].name}`}
                    >
                      {n > 0 ? n : ""}
                    </motion.div>
                  </td>
                ))}
                <td className="p-0">
                  <div
                    className="flex h-8 items-center justify-center rounded-md border border-dashed border-grey-300 text-[13px] font-semibold tabular-nums text-grey-700"
                    title={`${row.dimension}: ${row.absent} expected mechanism${row.absent === 1 ? "" : "s"} absent`}
                  >
                    {row.absent || ""}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
