import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary";

/** The button look, for a link that should read as a button. */
export function buttonClasses(variant: Variant = "primary") {
  const look =
    variant === "primary"
      ? "bg-black text-white hover:bg-grey-800"
      : "border border-black/20 text-black hover:bg-black/5";
  return `pressable inline-flex items-center justify-center rounded-xl px-5 py-2.5 text-sm font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black disabled:cursor-not-allowed disabled:opacity-50 ${look}`;
}

/** The app's one button. Primary is black on white; secondary is outlined.
 *  Replaces a WebGL "specular" button that opened a canvas per instance,
 *  which is heavy for a button and fails quietly on weaker devices. */
export default function Button({
  variant = "primary",
  className = "",
  type = "button",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type={type}
      className={`${buttonClasses(variant)} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
