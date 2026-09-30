import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

/**
 * Re-themed onto MedConf tokens.
 * Square-ish (4px) rather than fully rounded — pill-everything is the fastest
 * way to make an interface look templated. Tints come from the semantic
 * token triples (`--x-subtle` fill, `--x-border` hairline, `--x-text` label)
 * so every variant holds AA contrast in both themes.
 */
const badgeVariants = cva(
  [
    "inline-flex w-fit shrink-0 items-center justify-center gap-1 rounded-sm border",
    "px-1.5 py-0.5 text-[0.6875rem] leading-4 font-medium whitespace-nowrap",
    "transition-colors duration-150",
    "[&>svg]:pointer-events-none [&>svg]:size-3",
  ],
  {
    variants: {
      variant: {
        neutral: "border-border bg-surface-muted text-fg-muted",
        outline: "border-border bg-transparent text-fg-muted",
        solid: "border-transparent bg-fg text-bg",
        brand: "border-brand-border bg-brand-subtle text-brand-text",
        success: "border-ok-border bg-ok-subtle text-ok-text",
        warning: "border-warn-border bg-warn-subtle text-warn-text",
        danger: "border-danger-border bg-danger-subtle text-danger-text",
        info: "border-info-border bg-info-subtle text-info-text",
        conference:
          "border-type-conference-border bg-type-conference-subtle text-type-conference-text",
        course:
          "border-type-course-border bg-type-course-subtle text-type-course-text",
        workshop:
          "border-type-workshop-border bg-type-workshop-subtle text-type-workshop-text",
      },
      size: {
        default: "h-5",
        lg: "h-6 px-2 text-xs",
      },
    },
    defaultVariants: {
      variant: "neutral",
      size: "default",
    },
  }
)

function Badge({
  className,
  variant = "neutral",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant, size }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
