import type { ReactNode } from "react";

/** Every page's heading, one way, and static. The five pages used to open
 *  with four different effects (two of them pulling in GSAP and WebGL for a
 *  title); the Analysis heading had already been made static on request, so
 *  static is the one they now share.
 *
 *  `aside` sits at the right (the Analysis page's Ask AI button) and is
 *  mirrored by an empty column on the left so the title stays centred.
 *  Below `sm` there is no room for either column, so it drops under the
 *  subtitle instead.
 *  `compact` is the left-aligned, smaller form for the Auditor, whose page
 *  is a full-height chat rather than a document. */
export default function PageHeader({
  title,
  subtitle,
  aside,
  compact = false,
}: {
  title: string;
  subtitle?: ReactNode;
  aside?: ReactNode;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-black">
          {title}
        </h1>
        {subtitle && <p className="mt-1 text-sm text-grey-700">{subtitle}</p>}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:gap-0">
      <div aria-hidden className={aside ? "hidden w-24 shrink-0 sm:block" : "hidden"} />
      <div className="min-w-0 flex-1 text-center">
        <h1 className="text-[clamp(2.5rem,7vw,4rem)] font-extrabold leading-[1.05] tracking-tight text-black">
          {title}
        </h1>
        {subtitle && <p className="mx-auto mt-3 max-w-2xl text-grey-700">{subtitle}</p>}
      </div>
      {aside && <div className="flex shrink-0 sm:w-24 sm:justify-end">{aside}</div>}
    </div>
  );
}
