import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { api, errorMessage, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { useAuth } from "@/auth/AuthContext";
import { canReadResource } from "@/auth/permissions";
import { FieldError } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { ContactPicker } from "./ContactPicker";
import { GroupPicker } from "./GroupPicker";

export type User = components["schemas"]["UserOut"];

const optionalEmail = z.string().trim().refine((v) => v === "" || z.email().safeParse(v).success, "Enter a valid email");

const createSchema = z
  .object({
    username: z.string().trim().min(1, "Enter a username").max(64, "At most 64 characters"),
    password: z.string().min(10, "At least 10 characters").max(256),
    is_active: z.boolean(),
    mode: z.enum(["new", "existing"]),
    name: z.string().trim(),
    email: optionalEmail,
    contactId: z.number().nullable(),
    groupIds: z.array(z.number()),
  })
  .superRefine((v, ctx) => {
    if (v.mode === "new" && v.name === "") ctx.addIssue({ code: "custom", path: ["name"], message: "Enter a full name" });
    if (v.mode === "existing" && v.contactId === null) ctx.addIssue({ code: "custom", path: ["contactId"], message: "Choose a contact" });
  });
type CreateValues = z.infer<typeof createSchema>;

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => Promise.all(["users", "contacts"].map((key) => queryClient.invalidateQueries({ queryKey: [key] })));
}

export function CreateUserDialog({ onClose }: { onClose: () => void }) {
  const { can, permissions } = useAuth();
  const invalidate = useInvalidate();
  const [failure, setFailure] = useState<string | null>(null);
  const canCreateContact = can("contacts:create");
  const canLinkContact = canReadResource(permissions, "contacts");
  const {
    register, control, watch, handleSubmit, formState: { errors },
  } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      username: "", password: "", is_active: true, name: "", email: "", contactId: null, groupIds: [],
      mode: canCreateContact ? "new" : "existing",
    },
  });
  const mode = watch("mode");

  const create = useMutation({
    mutationFn: (v: CreateValues) => {
      const base = { username: v.username, password: v.password, is_active: v.is_active, group_ids: v.groupIds };
      return unwrap(
        api.POST("/users", {
          body:
            v.mode === "new"
              ? { ...base, contact: { name: v.name, email: v.email || null, type: "person", phones: [] } }
              : { ...base, contact_id: v.contactId },
        }),
      );
    },
    onSuccess: async () => {
      await invalidate();
      onClose();
    },
    onError: (err) => setFailure(errorMessage(err)),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && !create.isPending && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New user</DialogTitle>
          <DialogDescription>A user is a contact who can sign in. Phone numbers are managed on the Contacts page.</DialogDescription>
        </DialogHeader>
        <form
          noValidate
          className="space-y-4"
          onSubmit={handleSubmit((values: CreateValues) => {
            setFailure(null);
            create.mutate(values);
          })}
        >
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="user-username">Username</Label>
              <Input id="user-username" autoComplete="off" {...register("username")} />
              <FieldError message={errors.username?.message} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="user-password">Password</Label>
              <Input id="user-password" type="password" autoComplete="new-password" {...register("password")} />
              <FieldError message={errors.password?.message} />
            </div>
          </div>
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-medium">Contact</legend>
            <div className="flex gap-4 text-sm">
              {canCreateContact && (
                <label className="flex items-center gap-2">
                  <input type="radio" value="new" {...register("mode")} />
                  New contact
                </label>
              )}
              {canLinkContact && (
                <label className="flex items-center gap-2">
                  <input type="radio" value="existing" {...register("mode")} />
                  Existing contact
                </label>
              )}
            </div>
            {mode === "new" ? (
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="user-name">Full name</Label>
                  <Input id="user-name" {...register("name")} />
                  <FieldError message={errors.name?.message} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="user-email">Email</Label>
                  <Input id="user-email" type="email" {...register("email")} />
                  <FieldError message={errors.email?.message} />
                </div>
              </div>
            ) : (
              <Controller
                control={control}
                name="contactId"
                render={({ field }) => (
                  <>
                    <ContactPicker value={field.value} onChange={(c) => field.onChange(c.id)} />
                    <FieldError message={errors.contactId?.message} />
                  </>
                )}
              />
            )}
          </fieldset>
          <Controller control={control} name="groupIds" render={({ field }) => <GroupPicker value={field.value} onChange={field.onChange} />} />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" {...register("is_active")} />
            Active
          </label>
          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {failure}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={onClose} disabled={create.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              Create user
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const editSchema = z.object({
  username: z.string().trim().min(1, "Enter a username").max(64, "At most 64 characters"),
  is_active: z.boolean(),
  name: z.string().trim(),
  email: optionalEmail,
  groupIds: z.array(z.number()),
});
type EditValues = z.infer<typeof editSchema>;

export function EditUserDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const { can, me } = useAuth();
  const invalidate = useInvalidate();
  const [failure, setFailure] = useState<string | null>(null);
  const editsContact = can("contacts:update");
  const isSelf = me?.id === user.id;
  const initialGroups = user.groups.map((g) => g.id);
  const {
    register, control, handleSubmit, formState: { errors },
  } = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      username: user.username, is_active: user.is_active, name: user.name, email: user.email ?? "", groupIds: initialGroups,
    },
  });

  const save = useMutation({
    mutationFn: (v: EditValues) => {
      // Send only what changed, so an untouched group the caller could not assign cannot block a rename.
      const body: components["schemas"]["UserUpdate"] = {};
      if (v.username !== user.username) body.username = v.username;
      if (v.is_active !== user.is_active) body.is_active = v.is_active;
      if (editsContact && v.name !== user.name) body.name = v.name;
      if (editsContact && v.email !== (user.email ?? "")) body.email = v.email || null;
      const same = [...v.groupIds].sort().join() === [...initialGroups].sort().join();
      if (!same) body.group_ids = v.groupIds;
      if (Object.keys(body).length === 0) return Promise.resolve(null);
      return unwrap(api.PUT("/users/{user_id}", { params: { path: { user_id: user.id } }, body }));
    },
    onSuccess: async () => {
      await invalidate();
      onClose();
    },
    onError: (err) => setFailure(errorMessage(err)),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && !save.isPending && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit user</DialogTitle>
          <DialogDescription>Changing groups takes effect on the user's next request.</DialogDescription>
        </DialogHeader>
        <form
          noValidate
          className="space-y-4"
          onSubmit={handleSubmit((values: EditValues) => {
            setFailure(null);
            save.mutate(values);
          })}
        >
          <div className="space-y-1.5">
            <Label htmlFor="edit-username">Username</Label>
            <Input id="edit-username" {...register("username")} />
            <FieldError message={errors.username?.message} />
          </div>
          {editsContact && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="edit-name">Full name</Label>
                <Input id="edit-name" {...register("name")} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="edit-email">Email</Label>
                <Input id="edit-email" type="email" {...register("email")} />
                <FieldError message={errors.email?.message} />
              </div>
            </div>
          )}
          <Controller control={control} name="groupIds" render={({ field }) => <GroupPicker value={field.value} onChange={field.onChange} />} />
          <div className="flex items-center gap-2 text-sm">
            <label className="flex items-center gap-2">
              <input type="checkbox" disabled={isSelf} {...register("is_active")} />
              Active
            </label>
            {isSelf && <span className="text-xs text-muted-foreground">(you cannot deactivate yourself)</span>}
          </div>
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
