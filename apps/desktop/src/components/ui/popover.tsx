import * as P from "@radix-ui/react-popover";
import type { ReactNode } from "react";

export function Popover({ trigger, children, side = "top", align = "start" }: { trigger: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right"; align?: "start" | "center" | "end" }) {
  return (
    <P.Root>
      <P.Trigger asChild>{trigger}</P.Trigger>
      <P.Portal>
        <P.Content side={side} align={align} sideOffset={4} className="z-50 rounded-[var(--radius)] border border-line bg-panel p-3 shadow-[0_8px_24px_rgba(0,0,0,0.28)] outline-none">
          {children}
        </P.Content>
      </P.Portal>
    </P.Root>
  );
}
