import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { api, errorMessage, unwrap } from "@/api/client";
import { FieldError } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ContactPicker, type PickableContact } from "@/features/users/ContactPicker";

export const MAX_LENGTH = 1600; // ten SMS segments: the API's limit

const schema = z
  .object({
    contactId: z.number().nullable(),
    phone: z.string(),
    content: z.string().refine((v) => v.trim() !== "", "Enter a message").refine((v) => v.length <= MAX_LENGTH, `At most ${MAX_LENGTH} characters`),
  })
  .superRefine((v, ctx) => {
    if (v.contactId === null) ctx.addIssue({ code: "custom", path: ["contactId"], message: "Choose a contact" });
  });
type Values = z.infer<typeof schema>;

/** Compose and queue an outbound SMS (the "Create" action for messages). */
export function SendMessageDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [contact, setContact] = useState<PickableContact | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const {
    register, control, setValue, watch, handleSubmit, formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { contactId: null, phone: "", content: "" } });
  const length = watch("content").length;

  const send = useMutation({
    mutationFn: (v: Values) =>
      unwrap(api.POST("/messages/send", { body: { contact_id: v.contactId!, phone: v.phone || undefined, content: v.content } })),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["messages"] });
      onClose();
    },
    onError: (err) => setFailure(errorMessage(err)),
  });

  function choose(picked: PickableContact, onChange: (id: number) => void) {
    setContact(picked);
    onChange(picked.id);
    setValue("phone", (picked.phones.find((p) => p.is_primary) ?? picked.phones[0]).phone);
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !send.isPending && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New message</DialogTitle>
          <DialogDescription>The message is queued and sent by the GSM worker; its status updates on the list.</DialogDescription>
        </DialogHeader>
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
              name="contactId"
              render={({ field }) => <ContactPicker purpose="message" value={field.value} onChange={(c) => choose(c, field.onChange)} />}
            />
            <FieldError message={errors.contactId?.message} />
          </fieldset>
          {contact && (
            <div className="space-y-1.5">
              <Label htmlFor="message-phone">Phone number</Label>
              <Select id="message-phone" {...register("phone")}>
                {contact.phones.map((p) => (
                  <option key={p.phone} value={p.phone}>
                    {p.phone}
                    {p.label ? ` (${p.label})` : ""}
                  </option>
                ))}
              </Select>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="message-content">Message</Label>
            <Textarea id="message-content" {...register("content")} />
            <div className="flex justify-between">
              <FieldError message={errors.content?.message} />
              <span className="ml-auto text-xs text-muted-foreground">{length} / {MAX_LENGTH}</span>
            </div>
          </div>
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
              Send
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
