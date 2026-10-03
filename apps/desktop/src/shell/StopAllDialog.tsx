import { useControl } from "@/api/actions";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useUi } from "@/state/ui";

/** Agents → Stop all: kill switch behind a confirm dialog (Windows convention, UI.md §2). */
export function StopAllDialog() {
  const open = useUi((s) => s.stopOpen);
  const setOpen = useUi((s) => s.setStopOpen);
  const control = useControl();
  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title="Stop everything?"
      width={440}
      footer={
        <>
          <Button
            variant="danger"
            onClick={() => {
              control.mutate({ key: "kill_switch", value: true });
              setOpen(false);
            }}
          >
            Stop all agents and uploads
          </Button>
          <Button variant="primary" onClick={() => setOpen(false)}>
            Keep running
          </Button>
        </>
      }
    >
      <p className="m-0">
        Running agent sessions are interrupted, queued work is held and no uploads or submissions start until you turn the kill switch off again
        (Agents menu or tray). Scheduled posts stay scheduled.
      </p>
    </Dialog>
  );
}
