import { useEffect, type ReactNode } from "react";
import { popoutReady } from "@/lib/tauri";

/** A pop-out window starts hidden. Once this has rendered and the browser has drawn two frames, the desktop
 * app is asked to show it, so a pop-out never opens as a blank rectangle. In a browser tab it does nothing. */
export function PopoutShell({ children }: { children: ReactNode }) {
  useEffect(() => {
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => void popoutReady());
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, []);
  return <>{children}</>;
}
