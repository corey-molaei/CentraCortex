import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "./cn";

type AlertVariant = "info" | "success" | "warning" | "danger";

type AlertProps = HTMLAttributes<HTMLDivElement> & {
  variant?: AlertVariant;
  title?: string;
  children?: ReactNode;
};

const variantClasses: Record<AlertVariant, string> = {
  info: "border-blue-400/40 bg-blue-500/10 text-blue-100",
  success: "border-emerald-400/40 bg-emerald-500/10 text-emerald-100",
  warning: "border-amber-400/40 bg-amber-500/10 text-amber-100",
  danger: "border-red-400/40 bg-red-500/10 text-red-100"
};

export function Alert({ variant = "info", title, className, children, ...props }: AlertProps) {
  return (
    <div className={cn("rounded-xl border p-3", variantClasses[variant], className)} {...props}>
      {title && <p className="mb-1 text-sm font-semibold">{title}</p>}
      {children}
    </div>
  );
}
