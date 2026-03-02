import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { sessionStore } from "../api/session";

export function AuthGuard({ children }: { children: ReactNode }) {
  const token = sessionStore.getAccessToken();
  if (!token) {
    return <Navigate replace to="/login" />;
  }
  return <>{children}</>;
}
