import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

type Variant = "default" | "primary" | "ghost" | "danger";
type Size = "md" | "sm";

const variants: Record<Variant, string> = {
  default: "border border-line bg-panel-2 hover:bg-[color-mix(in_srgb,var(--panel-2)_80%,var(--fg)_8%)]",
  primary: "border border-transparent bg-accent text-accent-ink hover:brightness-110",
  ghost: "border border-transparent bg-transparent hover:bg-[color-mix(in_srgb,var(--fg)_7%,transparent)]",
  danger: "border border-line bg-panel-2 text-bad hover:bg-bad-soft",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  shortcut?: string;
};

/** 28px (24px small) native-looking button, 4px corners. Copy is verb-first, sentence case. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", size = "md", icon, shortcut, className, children, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-[var(--radius)] px-2.5 leading-none",
        "disabled:pointer-events-none disabled:opacity-45",
        size === "md" ? "h-[var(--control)]" : "h-[var(--control-sm)] px-2",
        variants[variant],
        className,
      )}
      {...rest}
    >
      {icon && <span className="inline-flex size-4 items-center justify-center [&_svg]:size-4">{icon}</span>}
      {children}
      {shortcut && <span className={cn("num text-[11px]", variant === "primary" ? "opacity-70" : "text-muted")}>{shortcut}</span>}
    </button>
  );
});
