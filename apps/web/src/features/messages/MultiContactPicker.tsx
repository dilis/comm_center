import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";

import { api, errorMessage, unwrap } from "@/api/client";
import { SearchBox } from "@/components/SearchBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { PickableContact } from "@/features/users/ContactPicker";

const PAGE_SIZE = 100; // the API's largest page

/** Search contacts and tick any number of them. Only contacts with a phone number are offered,
 *  and the selection is kept while you search for others. */
export function MultiContactPicker({
  selected, onChange,
}: { selected: PickableContact[]; onChange: (contacts: PickableContact[]) => void }) {
  const [q, setQ] = useState("");
  const contacts = useQuery({
    queryKey: ["contacts", "message-picker", q],
    queryFn: () =>
      unwrap(api.GET("/contacts", { params: { query: { q: q || undefined, page_size: PAGE_SIZE, sort: "name", order: "asc" } } })),
  });
  const choices = contacts.data?.items.filter((c) => c.phones.length > 0) ?? [];
  const total = contacts.data?.total ?? 0;
  const chosen = new Set(selected.map((c) => c.id));

  const toggle = (contact: PickableContact) =>
    onChange(chosen.has(contact.id) ? selected.filter((c) => c.id !== contact.id) : [...selected, contact]);
  const selectAllShown = () => onChange([...selected, ...choices.filter((c) => !chosen.has(c.id))]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <SearchBox label="Find contacts" value={q} onChange={setQ} />
        <Button variant="outline" size="sm" onClick={selectAllShown} disabled={choices.length === 0}>
          Select all shown
        </Button>
        {selected.length > 0 && (
          <Button variant="ghost" size="sm" onClick={() => onChange([])}>
            Clear selection
          </Button>
        )}
      </div>
      {contacts.error && (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage(contacts.error)}
        </p>
      )}
      <div role="group" aria-label="Contacts" className="max-h-44 space-y-1 overflow-y-auto rounded-md border p-2">
        {choices.map((c) => (
          <label key={c.id} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={chosen.has(c.id)} onChange={() => toggle(c)} />
            <span>{c.name}</span>
            <span className="text-xs text-muted-foreground">{(c.phones.find((p) => p.is_primary) ?? c.phones[0]).phone}</span>
          </label>
        ))}
        {contacts.data && choices.length === 0 && (
          <p className="text-xs text-muted-foreground">No contacts with a phone number found.</p>
        )}
      </div>
      {total > PAGE_SIZE && (
        <p className="text-xs text-muted-foreground">Showing the first {PAGE_SIZE} of {total} contacts; search to narrow it down.</p>
      )}
      {selected.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium">{selected.length} selected</p>
          <ul className="flex max-h-20 flex-wrap gap-1 overflow-y-auto">
            {selected.map((c) => (
              <li key={c.id}>
                <Badge variant="outline" className="gap-1">
                  {c.name}
                  <button type="button" aria-label={`Remove ${c.name}`} onClick={() => toggle(c)} className="hover:text-destructive">
                    <X className="h-3 w-3" aria-hidden />
                  </button>
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
