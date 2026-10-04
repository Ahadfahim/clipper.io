import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const fieldBase =
  "rounded-[var(--radius)] border border-line border-b-muted bg-bg px-2 outline-none focus:border-b-accent focus:border-b-2 disabled:opacity-50";

/** Underline-style text field (Windows): hairline box, darker bottom edge, accent on focus. */
export const TextField = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function TextField(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={cn(fieldBase, "h-[var(--control)] min-w-0", className)} {...rest} />;
});

export const TextArea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function TextArea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={cn(fieldBase, "min-w-0 resize-y py-1.5", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={cn(fieldBase, "h-[var(--control)] min-w-0 pr-1", className)} {...rest}>
      {children}
    </select>
  );
});

/** On/off control: always a checkbox, never a pill switch (UI.md §1). */
export function Check({
  checked,
  onChange,
  label,
  disabled,
  className,
  title,
  dim,
}: {
  checked: boolean;
  onChange?: (v: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
  className?: string;
  title?: string;
  dim?: boolean;
}) {
  return (
    <label
      title={title}
      className={cn("inline-flex h-[var(--control-sm)] items-center gap-1.5 px-1", (disabled || dim) && "text-faint", className)}
    >
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange?.(e.target.checked)} />
      <span className="truncate-1">{label}</span>
    </label>
  );
}

export function Radio({
  name,
  checked,
  onChange,
  label,
  disabled,
}: {
  name: string;
  checked: boolean;
  onChange: () => void;
  label: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className={cn("inline-flex items-center gap-1.5", disabled && "text-faint")}>
      <input type="radio" name={name} checked={checked} disabled={disabled} onChange={onChange} />
      {label}
    </label>
  );
}

/** Label above a control; `hint` renders muted below. */
export function Field({
  label,
  hint,
  children,
  className,
  id,
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: (id: string) => ReactNode;
  className?: string;
  id?: string;
}) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={fid} className="text-muted">
        {label}
      </label>
      {children(fid)}
      {hint && <span className="text-[11px] text-muted">{hint}</span>}
    </div>
  );
}

export function Fieldset({ legend, children, className }: { legend: ReactNode; children: ReactNode; className?: string }) {
  return (
    <fieldset className={cn("m-0 flex flex-col gap-1.5 rounded-[var(--radius)] border border-line px-3 pt-1.5 pb-2.5", className)}>
      <legend className="px-1 text-muted">{legend}</legend>
      {children}
    </fieldset>
  );
}
