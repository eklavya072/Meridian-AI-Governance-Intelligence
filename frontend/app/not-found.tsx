import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import { buttonClasses } from "@/components/Button";

/* Also the static export's 404.html, which the API serves for any path the
   app doesn't have. */
export default function NotFound() {
  return (
    <div className="py-16">
      <PageHeader
        title="Page not found"
        subtitle="There is nothing at this address. The link may be mistyped, or the page may have moved."
      />
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link href="/analysis" className={buttonClasses("primary")}>
          See the analyses
        </Link>
        <Link href="/" className={buttonClasses("secondary")}>
          Home
        </Link>
      </div>
    </div>
  );
}
