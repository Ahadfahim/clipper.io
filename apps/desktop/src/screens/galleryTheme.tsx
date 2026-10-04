import { Radio } from "@/components/ui/fields";
import { useUi } from "@/state/ui";

/** Theme switch for the gallery toolbar (also exercises the theme override). */
export function useAppearanceToggle() {
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  return (
    <span className="flex gap-3">
      {(["system", "light", "dark"] as const).map((t) => (
        <Radio key={t} name="gallery-theme" checked={theme === t} onChange={() => setTheme(t)} label={t} />
      ))}
    </span>
  );
}
