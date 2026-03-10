import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const getSession = vi.fn();
const getCurrentTenant = vi.fn();

vi.mock("./api/client", () => ({
  getSession: (...args: unknown[]) => getSession(...args),
  getCurrentTenant: (...args: unknown[]) => getCurrentTenant(...args)
}));

describe("App routing", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    getSession.mockResolvedValue({
      email: "user@example.com",
      full_name: "User",
      tenant_id: "tenant-1",
      memberships: []
    });
    getCurrentTenant.mockResolvedValue({
      id: "tenant-1",
      name: "Tenant One",
      slug: "tenant-one",
      is_active: true
    });
  });

  it("shows login page when unauthenticated", () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByText("CentraCortex Login")).toBeInTheDocument();
  });

  it("renders dashboard shell when authenticated", () => {
    localStorage.setItem("cc_access_token", "token");
    localStorage.setItem("cc_tenant_id", "tenant-1");

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByText("CentraCortex")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    return waitFor(() => {
      expect(getSession).toHaveBeenCalled();
    });
  });

  it("shows Google connector in connectors hub", () => {
    localStorage.setItem("cc_access_token", "token");
    localStorage.setItem("cc_tenant_id", "tenant-1");

    render(
      <MemoryRouter initialEntries={["/connectors"]}>
        <App />
      </MemoryRouter>
    );

    const googleLinks = screen.getAllByRole("link", { name: /google/i });
    expect(googleLinks.some((link) => link.getAttribute("href") === "/connectors/google")).toBe(true);
  });
});
