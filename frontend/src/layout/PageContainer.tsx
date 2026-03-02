import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../components/ui/cn";

type PageContainerProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

export function PageContainer({ className, children, ...props }: PageContainerProps) {
  return (
    <div className={cn("mx-auto w-full max-w-[1400px] p-4 md:p-6", className)} {...props}>
      {children}
    </div>
  );
}
