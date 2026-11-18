import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, errorMessage, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { browserSubscription, permission, pushSupported, turnOff, turnOn } from "@/push/push";

const SUBSCRIPTION = ["push", "subscription"] as const;

function Note({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

/** The switch for notifications on this device. */
export function NotificationsSection() {
  const queryClient = useQueryClient();
  const [failure, setFailure] = useState<string | null>(null);
  const supported = pushSupported();
  const config = useQuery({ queryKey: ["push", "config"], queryFn: () => unwrap(api.GET("/auth/me/push")) });
  const subscription = useQuery({ queryKey: SUBSCRIPTION, queryFn: browserSubscription, enabled: supported });
  const change = useMutation({
    mutationFn: (on: boolean) => (on ? turnOn(config.data?.public_key ?? "") : turnOff()),
    onMutate: () => setFailure(null),
    onError: (err) => setFailure(errorMessage(err)),
    onSettled: () => queryClient.invalidateQueries({ queryKey: SUBSCRIPTION }),
  });

  if (config.isPending) return <Note>Loading…</Note>;
  if (config.isError) return <Note>Could not check notification settings.</Note>;
  if (!config.data.enabled) return <Note>Notifications are not set up on this server.</Note>;
  if (!supported)
    return (
      <Note>
        This browser cannot show notifications. On an iPhone, add this app to your Home Screen (Share, then Add to Home
        Screen) and open it from there.
      </Note>
    );
  if (subscription.isPending) return <Note>Loading…</Note>;
  const on = subscription.data != null;
  if (!on && permission() === "denied")
    return <Note>Notifications are blocked for this site. Allow them in your browser's settings, then reload.</Note>;

  return (
    <div className="space-y-3">
      <Note>
        {on
          ? "Notifications are on for this device: you will be told when a message arrives."
          : "Get a notification on this device when a message arrives. It says who it is from, never what it says."}
      </Note>
      {failure && (
        <p role="alert" className="text-sm text-destructive">
          {failure}
        </p>
      )}
      <Button type="button" variant={on ? "outline" : "default"} disabled={change.isPending} onClick={() => change.mutate(!on)}>
        {on ? "Turn off notifications" : "Turn on notifications"}
      </Button>
    </div>
  );
}
