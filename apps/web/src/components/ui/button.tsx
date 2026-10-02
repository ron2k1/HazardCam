import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

// shadcn/ui button (base-nova), restyled to the HUD: square, 1px outline, tracked uppercase.
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center gap-2 border font-mono uppercase whitespace-nowrap transition-colors duration-150 outline-none select-none focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-fg disabled:pointer-events-none disabled:opacity-35 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      variant: {
        default: "border-fg/85 bg-transparent text-fg hover:bg-fg hover:text-bg",
        solid: "border-fg bg-fg text-bg hover:bg-transparent hover:text-fg",
        ghost: "border-line text-muted hover:border-line-strong hover:text-fg",
        danger: "border-danger/70 text-danger hover:bg-danger hover:text-bg",
      },
      size: {
        default: "h-9 px-5 text-[11px] tracking-[0.18em]",
        sm: "h-7 px-3 text-[10px] tracking-[0.16em]",
        lg: "h-11 px-7 text-[12px] tracking-[0.2em]",
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
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
