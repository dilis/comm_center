import { formatDateTime } from "@/lib/utils";

import type { Message } from "./MessageDetailDialog";

/** The text handed to the share sheet: the SMS wrapped so a reader in another app can tell it is a forwarded SMS, and from or to whom. */
export function forwardText(m: Message): string {
  const inbound = m.direction === "inbound";
  const who = [m.contact_name, m.phone_number].filter(Boolean);
  const party = who.length === 2 ? `${who[0]} (${who[1]})` : who[0] ?? "unknown";
  const when = formatDateTime(inbound ? m.received_at : (m.sent_at ?? m.created_at));
  return [
    "--- Forwarded SMS ---",
    `${inbound ? "From" : "To"}: ${party}`,
    when ? `${inbound ? "Received" : "Sent"}: ${when}` : null,
    "",
    m.content,
    "--- End of forwarded SMS ---",
  ]
    .filter((line) => line !== null)
    .join("\n");
}
