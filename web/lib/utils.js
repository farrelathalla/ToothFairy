import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn `cn` helper: merge conditional class names + dedupe Tailwind utilities. */
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
