import * as React from "react"
import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-9 w-full min-w-0 rounded-md border border-border bg-surface px-3 py-1",
        "text-base md:text-sm text-fg shadow-xs",
        "transition-[border-color,box-shadow] duration-150",
        "placeholder:text-fg-subtle selection:bg-brand-subtle selection:text-fg-strong",
        "file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-fg",
        "outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-ring/35",
        "aria-invalid:border-danger aria-invalid:focus-visible:ring-danger/30",
        "disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-surface-muted",
        className
      )}
      {...props}
    />
  )
}

export { Input }
