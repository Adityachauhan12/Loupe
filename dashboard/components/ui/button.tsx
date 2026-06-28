import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium whitespace-nowrap " +
    "transition-all duration-150 active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-bg " +
    "[&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-primary-strong text-white shadow-[0_0_0_1px_rgba(124,124,245,0.4),0_8px_24px_-8px_rgba(99,102,241,0.6)] " +
          "hover:bg-primary hover:shadow-[0_0_0_1px_rgba(124,124,245,0.6),0_10px_30px_-8px_rgba(99,102,241,0.8)]",
        secondary:
          "bg-surface-2 text-fg border border-line hover:border-line-strong hover:bg-elevated",
        ghost: "text-muted hover:text-fg hover:bg-surface-2",
        outline:
          "border border-primary-strong/50 text-primary hover:bg-primary-soft/30",
        danger:
          "bg-error/15 text-error border border-error/30 hover:bg-error/25",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4",
        lg: "h-11 px-6 text-base",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
);
Button.displayName = "Button";

export { buttonVariants };
