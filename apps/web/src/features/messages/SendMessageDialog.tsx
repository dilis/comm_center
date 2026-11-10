import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { api, errorMessage, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { FieldError } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { PickableContact } from "@/features/users/ContactPicker";

import { ComposeField, contentSchema } from "./ComposeField";
import { MultiContactPicker } from "./MultiContactPicker";

export const MAX_RECIPIENTS = 500; // the API's limit

type BulkResult = components["schemas"]["BulkSendResult"];

const schema = z.object({
  contactIds: z.array(z.number()).min(1, "Choose at least one contact").max(MAX_RECIPIENTS, `At most ${MAX_RECIPIENTS} contacts at a time`),
  phone: z.string(),
  content: contentSchema,
});
type Values = z.infer<typeof schema>;

/** Compose and queue an outbound SMS to one contact (with a choice of number) or to many (each to
 *  its primary number): the "Create" action for messages. */
export function SendMessageDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<PickableContact[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<BulkResult | null>(null);
  const {
    register, control, setValue, handleSubmit, formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { contactIds: [], phone: "", content: "" } });
  const only = selected.length === 1 ? selected[0] : null;

  const send = useMutation({
    mutationFn: async (v: Values): Promise<BulkResult | null> => {
      if (v.contactIds.length === 1) {
        await unwrap(api.POST("/messages/send", { body: { contact_id: v.contactIds[0], phone: v.phone || undefined, content: v.content } }));
        return null;
      }
      return unwrap(api.POST("/messages/send-bulk", { body: { contact_ids: v.contactIds, content: v.content } }));
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["messages"] });
      if (result && result.skipped.length > 0) setOutcome(result);
      else onClose();
    },
    onError: (err) => setFailure(errorMessage(err)),
  });

  function pick(contacts: PickableContact[], onChange: (ids: number[]) => void) {
    setSelected(contacts);
    onChange(contacts.map((c) => c.id));
    if (contacts.length === 1) {
      const phones = contacts[0].phones;
      setValue("phone", (phones.find((p) => p.is_primary) ?? phones[0]).phone);
    }
  }

  const nameOf = (id: number) => selected.find((c) => c.id === id)?.name ?? `Contact ${id}`;

  return (
    <Dialog open onOpenChange={(open) => !open && !send.isPending && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New message</DialogTitle>
          <DialogDescription>
            Choose one or more contacts. Each message is queued separately and sent by the GSM worker; statuses update on the list.
          </DialogDescription>
        </DialogHeader>
        {outcome ? (
          <div className="space-y-4">
            <div role="status" className="space-y-2 text-sm">
              <p>
                Queued {outcome.queued.length} message{outcome.queued.length === 1 ? "" : "s"}.
              </p>
              <p className="font-medium">Not sent to {outcome.skipped.length}:</p>
              <ul className="list-disc pl-5">
                {outcome.skipped.map((s) => (
                  <li key={s.contact_id}>
                    {nameOf(s.contact_id)}: {s.reason}
                  </li>
                ))}
              </ul>
            </div>
            <DialogFooter>
              <Button onClick={onClose}>Done</Button>
            </DialogFooter>
          </div>
        ) : (
          <form
            noValidate
            className="space-y-4"
            onSubmit={handleSubmit((values: Values) => {
              setFailure(null);
              send.mutate(values);
            })}
          >
            <fieldset className="space-y-1.5">
              <legend className="mb-1 text-sm font-medium">To</legend>
              <Controller
                control={control}
                name="contactIds"
                render={({ field }) => <MultiContactPicker selected={selected} onChange={(contacts) => pick(contacts, field.onChange)} />}
              />
              <FieldError message={errors.contactIds?.message} />
            </fieldset>
            {only && (
              <div className="space-y-1.5">
                <Label htmlFor="message-phone">Phone number</Label>
                <Select id="message-phone" {...register("phone")}>
                  {only.phones.map((p) => (
                    <option key={p.phone} value={p.phone}>
                      {p.phone}
                      {p.label ? ` (${p.label})` : ""}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <Controller
              control={control}
              name="content"
              render={({ field }) => (
                <ComposeField id="message-content" value={field.value} onChange={field.onChange} error={errors.content?.message} previewFor={selected[0]} />
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
                {selected.length > 1 ? `Send to ${selected.length} contacts` : "Send"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
