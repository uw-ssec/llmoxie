import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"
import { Slot } from "radix-ui"

// Styled to the SSEC design system: sharp corners (UW brand), uppercase Encode Sans Compressed,
// and its three sizes (32, 40 and 48px).
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-none border-2 border-transparent bg-clip-padding font-ui text-sm leading-none font-semibold tracking-wide whitespace-nowrap uppercase transition-colors outline-none select-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary-hover",
        outline: "border-primary bg-transparent text-primary hover:bg-primary hover:text-primary-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-accent",
        ghost: "text-primary hover:bg-secondary",
        destructive: "bg-destructive text-white hover:bg-destructive/90 focus-visible:ring-destructive/40",
        link: "h-auto border-0 p-0 text-primary normal-case underline-offset-4 hover:underline",
        inverse: "bg-white text-primary hover:bg-secondary",
      },
      size: {
        default: "h-10 gap-2 px-5",
        sm: "h-8 gap-1.5 px-3 text-xs",
        lg: "h-12 gap-2 px-6",
        icon: "size-10",
        "icon-sm": "size-8",
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
