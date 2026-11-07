import type { components } from "@/api/schema";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { formatDateTime } from "@/lib/utils";

export type Message = components["schemas"]["MessageOut"];

export const directionLabel = (m: Pick<Message, "direction">) => (m.direction === "inbound" ? "Received" : "Sent");

export function MessageDetailDialog({ message, onClose }: { message: Message; onClose: () => void }) {
  const rows: [string, string | null][] = [
    ["Direction", directionLabel(message)],
    ["Contact", message.contact_name],
    ["Phone", message.phone_number],
    ["Status", message.status],
    ["Error", message.error_message],
    ["Created", formatDateTime(message.created_at)],
    ["Sent", formatDateTime(message.sent_at)],
    ["Received", formatDateTime(message.received_at)],
  ];
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Message</DialogTitle>
          <DialogDescription>Messages are a read-only log.</DialogDescription>
        </DialogHeader>
        <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1 text-sm">
          {rows
            .filter(([, value]) => value)
            .map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
        </dl>
        {/* SMS text is untrusted: rendered only as text, never as markup. */}
        <p className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-md border bg-muted p-3 text-sm">{message.content}</p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
