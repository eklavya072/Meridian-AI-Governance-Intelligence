"use client";

import type { ComponentType, ReactNode } from "react";
import SpecularButtonJs from "@/components/SpecularButton";
import palette from "@/lib/palette.json";

/* SpecularButton is untyped JavaScript, so its props are inferred from their
   defaults (a label of "Get Started" makes children a string). */
const SpecularButton = SpecularButtonJs as unknown as ComponentType<
  Record<string, unknown> & { children?: ReactNode }
>;

/** The primary action on a page: black, with a rim of light that turns to
 *  follow the pointer as it comes near (SpecularButton, WebGL). One per
 *  page — each is its own WebGL context. */
export default function ShineButton({
  children,
  onClick,
  disabled,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <SpecularButton
      className={`shine-button ${className}`}
      radius={12}
      tint={palette.black}
      tintOpacity={1}
      blur={0}
      textColor={palette.white}
      lineColor={palette.white}
      baseColor={palette.black}
      intensity={1.2}
      shineSize={10}
      shineFade={40}
      thickness={1.2}
      speed={0.35}
      followMouse
      proximity={250}
      autoAnimate={false}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </SpecularButton>
  );
}
