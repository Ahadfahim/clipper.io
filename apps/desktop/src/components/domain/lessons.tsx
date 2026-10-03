import { useState } from "react";
import { Button } from "@/components/ui/button";
import { TextArea } from "@/components/ui/fields";
import { Badge } from "@/components/ui/misc";
import { day } from "@/lib/format";
import type { Schemas } from "@/api/client";

/** One lesson the agents saved: text, scope, evidence; edit or delete (Settings → Memory). */
export function LessonRow({ lesson, onSave, onDelete }: { lesson: Schemas["LessonOut"]; onSave: (note: string) => void; onDelete: () => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <div className="flex items-start gap-2 border-b border-line-soft py-1 last:border-b-0">
      <Badge>{lesson.scope}</Badge>
      <div className="min-w-0 flex-1">
        {draft !== null ? (
          <TextArea aria-label="Lesson text" rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} className="w-full" />
        ) : (
          <div className="selectable">{lesson.note}</div>
        )}
        <div className="text-[11px] text-muted">
          {lesson.created_by} · {day(lesson.created_at)}
          {lesson.evidence_ref ? ` · evidence: ${lesson.evidence_ref}` : ""}
        </div>
      </div>
      {draft !== null ? (
        <>
          <Button size="sm" variant="primary" disabled={!draft.trim()} onClick={() => (onSave(draft.trim()), setDraft(null))}>
            Save
          </Button>
          <Button size="sm" onClick={() => setDraft(null)}>
            Cancel
          </Button>
        </>
      ) : (
        <Button size="sm" onClick={() => setDraft(lesson.note)}>
          Edit
        </Button>
      )}
      <Button size="sm" variant="danger" onClick={onDelete}>
        Delete
      </Button>
    </div>
  );
}
