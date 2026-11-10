import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { api, errorMessage, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { formatDateTime } from "@/lib/utils";

import { ComposeField, contentSchema } from "./ComposeField";
import type { Message } from "./MessageDetailDialog";

const schema = z.object({ content: contentSchema });
type Values = z.infer<typeof schema>;

/** Answer a received message: the text goes to the number it came from, linked to the original. */
export function ReplyDialog({ message, onClose }: { message: Message; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [failure, setFailure] = useState<string | null>(null);
  const {
    control, handleSubmit, formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { content: "" } });

  const send = useMutation({
    mutationFn: (v: Values) => unwrap(api.POST("/messages/{message_id}/reply", { params: { path: { message_id: message.id } }, body: { content: v.content } })),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["messages"] });
      onClose();
    },
    onError: (err) => setFailure(errorMessage(err)),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && !send.isPending && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reply</DialogTitle>
          <DialogDescription>
            To {message.contact_name}, at <span>{message.phone_number}</span>. It is queued and sent by the GSM worker.
          </DialogDescription>
        </DialogHeader>
        <blockquote className="space-y-1 rounded-md border-l-4 bg-muted p-3 text-sm">
          <p className="text-xs text-muted-foreground">
            {message.contact_name} wrote on {formatDateTime(message.received_at ?? message.created_at)}
          </p>
          {/* SMS text is untrusted: rendered only as text, never as markup. */}
          <p className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words">{message.content}</p>
        </blockquote>
        <form
          noValidate
          className="space-y-4"
          onSubmit={handleSubmit((values: Values) => {
            setFailure(null);
            send.mutate(values);
          })}
        >
          <Controller
            control={control}
            name="content"
            render={({ field }) => (
              <ComposeField id="reply-content" value={field.value} onChange={field.onChange} error={errors.content?.message} previewFor={{ name: message.contact_name, first_name: message.contact_first_name, last_name: message.contact_last_name }} />
            )}
          />
          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {failure}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={onClose} disabled={send.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={send.isPending}>
              Send reply
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
