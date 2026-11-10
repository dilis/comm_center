import type { FieldError as RhfFieldError, UseFormRegisterReturn } from "react-hook-form";
import { z } from "zod";

import { FieldError } from "@/components/PageHeader";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Form values for a person's name; middle and last are blank when there is none. */
export const nameShape = {
  first_name: z.string().trim().min(1, "Enter a first name").max(255, "At most 255 characters"),
  middle_name: z.string().trim().max(100, "At most 100 characters"),
  last_name: z.string().trim().max(100, "At most 100 characters"),
};

/** What the API takes for those values: a blank middle or last name is sent as ``null``. */
export function nameBody(v: { first_name: string; middle_name: string; last_name: string }) {
  return { first_name: v.first_name, middle_name: v.middle_name || null, last_name: v.last_name || null };
}

type Props = {
  idPrefix: string;
  first: UseFormRegisterReturn;
  middle: UseFormRegisterReturn;
  last: UseFormRegisterReturn;
  errors: { first_name?: RhfFieldError; middle_name?: RhfFieldError; last_name?: RhfFieldError };
  /** An entity has one name only (the first field, labelled "Name"). */
  single?: boolean;
};

/** First, middle (optional) and last name inputs. */
export function NameFields({ idPrefix, first, middle, last, errors, single = false }: Props) {
  return (
    <div className={single ? "space-y-1.5" : "grid grid-cols-1 gap-3 sm:grid-cols-3"}>
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-first-name`}>{single ? "Name" : "First name"}</Label>
        <Input id={`${idPrefix}-first-name`} autoComplete="off" {...first} />
        <FieldError message={errors.first_name?.message} />
      </div>
      {!single && (
        <>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}-middle-name`}>Middle name</Label>
            <Input id={`${idPrefix}-middle-name`} autoComplete="off" {...middle} />
            <FieldError message={errors.middle_name?.message} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}-last-name`}>Last name</Label>
            <Input id={`${idPrefix}-last-name`} autoComplete="off" {...last} />
            <FieldError message={errors.last_name?.message} />
          </div>
        </>
      )}
    </div>
  );
}
