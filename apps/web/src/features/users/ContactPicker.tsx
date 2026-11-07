import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, errorMessage, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { SearchBox } from "@/components/SearchBox";

export type PickableContact = components["schemas"]["ContactOut"];

/** Search contacts and choose one that is not yet a user (to link a new user to it). */
export function ContactPicker({ value, onChange }: { value: number | null; onChange: (contact: PickableContact) => void }) {
  const [q, setQ] = useState("");
  const contacts = useQuery({
    queryKey: ["contacts", "picker", q],
    queryFn: () => unwrap(api.GET("/contacts", { params: { query: { q: q || undefined, page_size: 10, sort: "name", order: "asc" } } })),
  });
  const choices = contacts.data?.items.filter((c) => !c.user_id) ?? [];
  return (
    <div className="space-y-2">
      <SearchBox label="Find a contact" value={q} onChange={setQ} />
      {contacts.error && (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage(contacts.error)}
        </p>
      )}
      <div role="radiogroup" aria-label="Contacts" className="max-h-40 space-y-1 overflow-y-auto">
        {choices.map((c) => (
          <label key={c.id} className="flex items-center gap-2 text-sm">
            <input type="radio" name="existing-contact" checked={value === c.id} onChange={() => onChange(c)} />
            <span>{c.name}</span>
            {c.email && <span className="text-xs text-muted-foreground">{c.email}</span>}
          </label>
        ))}
        {contacts.data && choices.length === 0 && (
          <p className="text-xs text-muted-foreground">No available contacts. Contacts that already have a user are not listed.</p>
        )}
      </div>
    </div>
  );
}
