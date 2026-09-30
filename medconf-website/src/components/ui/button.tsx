import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

/**
 * Re-themed onto MedConf tokens (see globals.css).
 * - one solid brand colour for primary actions, never a gradient
 * - 6px radius, 1px hairline borders, shadow only on raised/outline variants
 * - every variant is pointer/hover/focus-visible/disabled complete
 */
const buttonVariants = cva(
  [
    "inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-md",
    "font-medium whitespace-nowrap select-none",
    "transition-[background-color,border-color,color,box-shadow,opacity] duration-150 ease-out",
    "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
    "disabled:pointer-events-none disabled:opacity-45",
    "aria-invalid:border-danger",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  ],
  {
    variants: {
      variant: {
        default:
          "bg-brand text-fg-onbrand hover:bg-brand-hover active:bg-brand-active",
        // Quiet primary: brand meaning without brand weight. Used for chips
        // and selected states in the directory.
        subtle:
          "bg-brand-subtle text-brand-text hover:bg-brand-subtle-hover border border-brand-border",
        outline:
          "border border-border bg-surface text-fg shadow-xs hover:bg-surface-hover hover:border-border-strong active:bg-surface-active",
        secondary:
          "bg-surface-muted text-fg hover:bg-surface-active border border-transparent",
        ghost:
          "text-fg-muted hover:bg-surface-hover hover:text-fg active:bg-surface-active",
        link:
          "text-brand-text underline-offset-4 hover:underline px-0",
        destructive:
          "bg-danger text-white hover:opacity-90 active:opacity-80 focus-visible:ring-danger",
      },
      size: {
        default: "h-9 px-3.5 text-sm has-[>svg]:px-3",
        sm: "h-8 gap-1.5 px-3 text-[0.8125rem] has-[>svg]:px-2.5",
        xs: "h-7 gap-1 rounded-sm px-2 text-xs [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-11 px-5 text-[0.9375rem]",
        icon: "size-9",
        "icon-sm": "size-8",
        "icon-lg": "size-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
