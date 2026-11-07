import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";

/** A search field that reports its value after a short pause, so typing does not fire a request
 *  per keystroke. Re-syncs when the value changes from outside (Back, a shared link). */
export function SearchBox({
  value, onChange, label, placeholder, delay = 250,
}: { value: string; onChange: (value: string) => void; label: string; placeholder?: string; delay?: number }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  useEffect(() => {
    if (text === value) return;
    const timer = setTimeout(() => onChange(text), delay);
    return () => clearTimeout(timer);
  }, [text, value, onChange, delay]);
  return (
    <Input
      type="search"
      aria-label={label}
      placeholder={placeholder ?? label}
      className="w-64"
      value={text}
      onChange={(e) => setText(e.target.value)}
    />
  );
}
