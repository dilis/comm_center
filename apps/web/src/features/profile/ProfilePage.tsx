import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";

import { api, errorMessage, unwrap } from "@/api/client";
import { useAuth, type Me } from "@/auth/AuthContext";
import { NameFields, nameBody, nameShape } from "@/components/NameFields";
import { FieldError, PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { NotificationsSection } from "./NotificationsSection";
import { SessionsSection } from "./SessionsSection";

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-md border bg-card p-4 sm:p-5">
      <h2 className="text-base font-semibold">{title}</h2>
      {description && <p className="mb-3 text-sm text-muted-foreground">{description}</p>}
      <div className={description ? "" : "mt-3"}>{children}</div>
    </section>
  );
}

function Feedback({ failure, done }: { failure: string | null; done: string | null }) {
  if (failure)
    return (
      <p role="alert" className="text-sm text-destructive">
        {failure}
      </p>
    );
  return done ? (
    <p role="status" className="text-sm text-muted-foreground">
      {done}
    </p>
  ) : null;
}

const profileSchema = z.object({
  ...nameShape,
  email: z.string().trim().refine((v) => v === "" || z.email().safeParse(v).success, "Enter a valid email"),
});
type ProfileValues = z.infer<typeof profileSchema>;

function ProfileForm({ me, onSaved }: { me: Me; onSaved: (me: Me) => void }) {
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const {
    register, handleSubmit, formState: { errors },
  } = useForm<ProfileValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: { first_name: me.first_name, middle_name: me.middle_name ?? "", last_name: me.last_name ?? "", email: me.email ?? "" },
  });
  const save = useMutation({
    mutationFn: (v: ProfileValues) =>
      unwrap(
        api.PATCH("/auth/me/profile", {
          body: v.email ? { ...nameBody(v), email: v.email } : { ...nameBody(v), clear_email: true },
        }),
      ),
    onSuccess: (updated) => {
      onSaved(updated);
      setDone("Saved.");
    },
    onError: (err) => setFailure(errorMessage(err)),
  });
  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={handleSubmit((v: ProfileValues) => {
        setFailure(null);
        setDone(null);
        save.mutate(v);
      })}
    >
      <NameFields idPrefix="profile" first={register("first_name")} middle={register("middle_name")} last={register("last_name")} errors={errors} />
      <div className="space-y-1.5">
        <Label htmlFor="profile-email">Email</Label>
        <Input id="profile-email" type="email" {...register("email")} />
        <FieldError message={errors.email?.message} />
      </div>
      <Feedback failure={failure} done={done} />
      <Button type="submit" disabled={save.isPending}>
        Save profile
      </Button>
    </form>
  );
}

const phonesSchema = z.object({
  phones: z.array(
    z.object({ phone: z.string(), label: z.string().max(32, "At most 32 characters"), is_primary: z.boolean() }),
  ),
});
type PhonesValues = z.infer<typeof phonesSchema>;

function PhonesForm({ me, onSaved }: { me: Me; onSaved: (me: Me) => void }) {
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const { register, control, watch, setValue, handleSubmit, formState: { errors } } = useForm<PhonesValues>({
    resolver: zodResolver(phonesSchema),
    defaultValues: { phones: me.phones.map((p) => ({ phone: p.phone, label: p.label ?? "", is_primary: p.is_primary })) },
  });
  const phones = useFieldArray({ control, name: "phones" });
  const watched = watch("phones");
  const save = useMutation({
    mutationFn: (v: PhonesValues) =>
      unwrap(
        api.PUT("/auth/me/phones", {
          body: {
            phones: v.phones
              .filter((p) => p.phone.trim() !== "")
              .map((p) => ({ phone: p.phone.trim(), label: p.label.trim() || null, is_primary: p.is_primary })),
          },
        }),
      ),
    onSuccess: (updated) => {
      onSaved(updated);
      setDone("Saved.");
    },
    onError: (err) => setFailure(errorMessage(err)),
  });
  return (
    <form
      noValidate
      className="space-y-3"
      onSubmit={handleSubmit((v: PhonesValues) => {
        setFailure(null);
        setDone(null);
        save.mutate(v);
      })}
    >
      {phones.fields.map((field, i) => (
        <div key={field.id} className="flex items-center gap-2">
          <Input aria-label={`Phone ${i + 1}`} placeholder="0917 123 4567" {...register(`phones.${i}.phone`)} />
          <Input aria-label={`Label ${i + 1}`} placeholder="Label" className="w-28" {...register(`phones.${i}.label`)} />
          <label className="flex items-center gap-1 text-xs">
            <input
              type="radio"
              name="primary-phone"
              aria-label={`Primary phone ${i + 1}`}
              checked={watched[i]?.is_primary ?? false}
              onChange={() => watched.forEach((_, j) => setValue(`phones.${j}.is_primary`, j === i))}
            />
            Primary
          </label>
          <Button type="button" variant="ghost" size="icon" aria-label={`Remove phone ${i + 1}`} onClick={() => phones.remove(i)}>
            <Trash2 className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      ))}
      <FieldError message={errors.phones?.message} />
      <div>
        <Button type="button" variant="outline" size="sm" onClick={() => phones.append({ phone: "", label: "", is_primary: false })}>
          <Plus className="h-4 w-4" aria-hidden />
          Add phone
        </Button>
      </div>
      <Feedback failure={failure} done={done} />
      <Button type="submit" disabled={save.isPending}>
        Save phone numbers
      </Button>
    </form>
  );
}

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Enter your current password"),
    new_password: z.string().min(10, "At least 10 characters").max(256),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "The passwords do not match" });
type PasswordValues = z.infer<typeof passwordSchema>;

function PasswordForm({ onChanged }: { onChanged: () => void }) {
  const [failure, setFailure] = useState<string | null>(null);
  const {
    register, handleSubmit, formState: { errors },
  } = useForm<PasswordValues>({ resolver: zodResolver(passwordSchema), defaultValues: { current_password: "", new_password: "", confirm: "" } });
  const change = useMutation({
    mutationFn: (v: PasswordValues) =>
      unwrap(api.PUT("/auth/me/password", { body: { current_password: v.current_password, new_password: v.new_password } })),
    onSuccess: onChanged,
    onError: (err) => setFailure(errorMessage(err)),
  });
  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={handleSubmit((v: PasswordValues) => {
        setFailure(null);
        change.mutate(v);
      })}
    >
      <div className="space-y-1.5">
        <Label htmlFor="pw-current">Current password</Label>
        <Input id="pw-current" type="password" autoComplete="current-password" {...register("current_password")} />
        <FieldError message={errors.current_password?.message} />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="pw-new">New password</Label>
          <Input id="pw-new" type="password" autoComplete="new-password" {...register("new_password")} />
          <FieldError message={errors.new_password?.message} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pw-confirm">Confirm new password</Label>
          <Input id="pw-confirm" type="password" autoComplete="new-password" {...register("confirm")} />
          <FieldError message={errors.confirm?.message} />
        </div>
      </div>
      <Feedback failure={failure} done={null} />
      <Button type="submit" disabled={change.isPending}>
        Change password
      </Button>
    </form>
  );
}

export default function ProfilePage() {
  const { me, setMe, logout, canAny } = useAuth();
  if (!me) return null;
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title="My profile" />
      <Section title="Account">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-[8rem_1fr]">
          <dt className="text-muted-foreground">Username</dt>
          <dd>{me.username}</dd>
          <dt className="text-muted-foreground">Groups</dt>
          <dd>{me.groups.length ? me.groups.join(", ") : "None"}</dd>
        </dl>
      </Section>
      <Section title="Personal details">
        <ProfileForm me={me} onSaved={setMe} />
      </Section>
      <Section title="Phone numbers">
        <PhonesForm me={me} onSaved={setMe} />
      </Section>
      {canAny(["messages:read_all", "messages:read_received"]) && (
        <Section title="Notifications">
          <NotificationsSection />
        </Section>
      )}
      <Section
        title="Sessions"
        description="Where you are signed in. A session stays listed until it is signed out, even if the browser is closed."
      >
        <SessionsSection />
      </Section>
      <Section title="Password" description="Changing your password signs you out everywhere, including here.">
        <PasswordForm onChanged={() => void logout()} />
      </Section>
    </div>
  );
}
