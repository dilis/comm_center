import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";

import { api, errorMessage, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { FieldError } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export type Contact = components["schemas"]["ContactOut"];

const schema = z.object({
  name: z.string().trim().min(1, "Enter a name").max(255, "At most 255 characters"),
  type: z.enum(["person", "entity"]),
  email: z.string().trim().refine((v) => v === "" || z.email().safeParse(v).success, "Enter a valid email"),
  notes: z.string(),
  phones: z.array(
    z.object({ phone: z.string(), label: z.string().max(32, "At most 32 characters"), is_primary: z.boolean() }),
  ),
});
type Values = z.infer<typeof schema>;

/** Create (no ``contact``) or edit a contact, including its phone numbers. */
export function ContactDialog({ contact, onClose }: { contact?: Contact; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [failure, setFailure] = useState<string | null>(null);
  const {
    register, control, handleSubmit, setValue, watch, formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: contact?.name ?? "",
      type: (contact?.type as Values["type"] | undefined) ?? "person",
      email: contact?.email ?? "",
      notes: contact?.notes ?? "",
      phones: (contact?.phones ?? []).map((p) => ({ phone: p.phone, label: p.label ?? "", is_primary: p.is_primary })),
    },
  });
  const phones = useFieldArray({ control, name: "phones" });
  const watched = watch("phones");

  const save = useMutation({
    mutationFn: (values: Values) => {
      const body = {
        name: values.name,
        type: values.type,
        email: values.email || null,
        notes: values.notes.trim() || null,
        phones: values.phones
          .filter((p) => p.phone.trim() !== "")
          .map((p) => ({ phone: p.phone.trim(), label: p.label.trim() || null, is_primary: p.is_primary })),
      };
      return contact
        ? unwrap(api.PUT("/contacts/{contact_id}", { params: { path: { contact_id: contact.id } }, body }))
        : unwrap(api.POST("/contacts", { body }));
    },
    onSuccess: async () => {
      // Names show up on users and messages too.
      await Promise.all(["contacts", "users", "messages"].map((key) => queryClient.invalidateQueries({ queryKey: [key] })));
      onClose();
    },
    onError: (err) => setFailure(errorMessage(err)),
  });

  const title = contact ? "Edit contact" : "New contact";
  return (
    <Dialog open onOpenChange={(open) => !open && !save.isPending && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Numbers are checked and stored in international format (E.164); numbers without a country code use the server's default region.
          </DialogDescription>
        </DialogHeader>
        <form
          noValidate
          className="space-y-4"
          onSubmit={handleSubmit((values: Values) => {
            setFailure(null);
            save.mutate(values);
          })}
        >
          <div className="space-y-1.5">
            <Label htmlFor="contact-name">Name</Label>
            <Input id="contact-name" {...register("name")} />
            <FieldError message={errors.name?.message} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="contact-type">Type</Label>
              <Select id="contact-type" disabled={!!contact?.user_id} {...register("type")}>
                <option value="person">person</option>
                <option value="entity">entity</option>
              </Select>
              {contact?.user_id ? <p className="text-xs text-muted-foreground">Belongs to a user, so it stays a person.</p> : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="contact-email">Email</Label>
              <Input id="contact-email" type="email" {...register("email")} />
              <FieldError message={errors.email?.message} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="contact-notes">Notes</Label>
            <Textarea id="contact-notes" {...register("notes")} />
          </div>
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">Phone numbers</legend>
            {phones.fields.map((field, i) => (
              <div key={field.id} className="flex items-start gap-2">
                <Input aria-label={`Phone ${i + 1}`} placeholder="0917 123 4567" {...register(`phones.${i}.phone`)} />
                <Input aria-label={`Label ${i + 1}`} placeholder="Label" className="w-28" {...register(`phones.${i}.label`)} />
                <label className="flex h-9 items-center gap-1 text-xs">
                  <input
                    type="radio"
                    name="primary-phone"
                    aria-label={`Primary ${i + 1}`}
                    checked={watched?.[i]?.is_primary ?? false}
                    onChange={() => watched.forEach((_, j) => setValue(`phones.${j}.is_primary`, j === i))}
                  />
                  Primary
                </label>
                <Button variant="ghost" size="icon" aria-label={`Remove phone ${i + 1}`} onClick={() => phones.remove(i)}>
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => phones.append({ phone: "", label: "", is_primary: false })}>
              <Plus className="h-4 w-4" aria-hidden />
              Add phone
            </Button>
          </fieldset>
          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {failure}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={onClose} disabled={save.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
