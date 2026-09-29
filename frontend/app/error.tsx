"use client";

import { useEffect } from "react";
import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import Button, { buttonClasses } from "@/components/Button";

/* Shown in place of a page that threw while rendering. The nav stays, so the
   reader can still go elsewhere; "Try again" re-renders the page. */
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="py-16">
      <PageHeader
        title="Something went wrong"
        subtitle="This page hit an error while loading. Trying again usually fixes it; if it doesn't, the details are in the browser console."
      />
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Button onClick={reset}>Try again</Button>
        <Link href="/" className={buttonClasses("secondary")}>
          Home
        </Link>
      </div>
    </div>
  );
}
