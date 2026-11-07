import { useRef } from "react";
import { z } from "zod";

import { FieldError } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { insertAt, placeholderError, renderPreview } from "@/lib/placeholders";

export const MAX_LENGTH = 1600; // ten SMS segments: the API's limit

/** The rules for message text, shared by the send and reply forms. */
export const contentSchema = z.string().superRefine((text, ctx) => {
  if (text.trim() === "") ctx.addIssue({ code: "custom", message: "Enter a message" });
  else {
    const unknown = placeholderError(text);
    if (unknown) ctx.addIssue({ code: "custom", message: unknown });
  }
  if (text.length > MAX_LENGTH) ctx.addIssue({ code: "custom", message: `At most ${MAX_LENGTH} characters` });
});

/** The message box: an "Insert name" button, a character counter, and a preview of the text as the
 *  first recipient will get it (the server fills in each recipient's own name). */
export function ComposeField({
  id, value, onChange, error, previewName,
}: { id: string; value: string; onChange: (text: string) => void; error?: string; previewName?: string }) {
  const box = useRef<HTMLTextAreaElement>(null);
  const preview = previewName ? renderPreview(value, previewName) : null;
  const showPreview = preview !== null && preview !== value;

  function insertName() {
    const el = box.current;
    const { text, cursor } = insertAt(value, el?.selectionStart ?? value.length, el?.selectionEnd ?? value.length, "{{name}}");
    onChange(text);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(cursor, cursor);
    });
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <Label htmlFor={id}>Message</Label>
        <Button variant="outline" size="sm" onClick={insertName}>
          Insert name
        </Button>
      </div>
      <Textarea id={id} ref={box} value={value} onChange={(e) => onChange(e.target.value)} />
      <p className="text-xs text-muted-foreground">
        Write <code>{"{{name}}"}</code> where each contact's name should go.
      </p>
      {showPreview && (
        <div data-testid="preview" className="space-y-1 rounded-md border bg-muted p-2 text-sm">
          <p className="text-xs font-medium text-muted-foreground">Preview for {previewName}</p>
          <p className="whitespace-pre-wrap break-words">{preview}</p>
          {preview.length > MAX_LENGTH && (
            <p className="text-xs text-destructive">Over {MAX_LENGTH} characters once the name is inserted</p>
          )}
        </div>
      )}
      <div className="flex justify-between">
        <FieldError message={error} />
        <span className="ml-auto text-xs text-muted-foreground">{value.length} / {MAX_LENGTH}</span>
      </div>
    </div>
  );
}
