import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

/** How long the pointer must rest on the element before the tooltip opens (milliseconds), so a
 *  mouse just passing by shows nothing. Keyboard focus opens it at once. A plain object so tests
 *  can shorten it. */
export const TIP = { delayMs: 500 };

/** A tooltip for hover and keyboard focus (the browser's own `title` tooltip never shows on touch
 *  and is clipped by scrolling tables). ``children`` must be a single focusable element. */
export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delayDuration={TIP.delayMs} skipDelayDuration={0}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            sideOffset={4}
            className="z-50 rounded-md border bg-background px-2 py-1 text-xs shadow-md"
          >
            {content}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}
