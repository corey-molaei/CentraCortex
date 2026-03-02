import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { DashboardLayout } from "./DashboardLayout";

vi.mock("../api/client", () => ({
  getSession: vi.fn().mockResolvedValue({
    user_id: "user-1",
    email: "admin@example.com",
    full_name: "Admin",
    tenant_id: "tenant-1",
    memberships: [
      {
        tenant_id: "tenant-1",
        tenant_name: "Acme Corp",
        role: "Owner"
      }
    ],
    issued_at: "2026-02-20T00:00:00Z"
  }),
  switchTenant: vi.fn()
}));

describe("DashboardLayout", () => {
  it("renders sidebar and highlights active route", async () => {
    localStorage.setItem("cc_tenant_id", "tenant-1");

    render(
      <MemoryRouter initialEntries={["/documents"]}>
        <Routes>
          <Route element={<DashboardLayout />}>
            <Route element={<div>Documents page content</div>} path="/documents" />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText("CentraCortex")).toBeInTheDocument();
    expect(screen.getByText("Documents page content")).toBeInTheDocument();

    const documentsNav = screen.getByRole("link", { name: "Documents" });
    await waitFor(() => {
      expect(documentsNav.className).toContain("bg-accent");
    });
  });
});
