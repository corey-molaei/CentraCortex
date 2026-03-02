import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GoogleConnectorPage } from "./GoogleConnectorPage";

const listGoogleAccounts = vi.fn();
const createGoogleAccount = vi.fn();
const updateGoogleAccount = vi.fn();
const deleteGoogleAccount = vi.fn();
const googleOAuthStart = vi.fn();
const googleOAuthCallback = vi.fn();
const googleTest = vi.fn();
const googleSync = vi.fn();
const googleStatus = vi.fn();
const googleListCalendars = vi.fn();
const createGoogleCalendarEvent = vi.fn();
const updateGoogleCalendarEvent = vi.fn();
const deleteGoogleCalendarEvent = vi.fn();

vi.mock("../../api/connectors", () => ({
  listGoogleAccounts: (...args: unknown[]) => listGoogleAccounts(...args),
  createGoogleAccount: (...args: unknown[]) => createGoogleAccount(...args),
  updateGoogleAccount: (...args: unknown[]) => updateGoogleAccount(...args),
  deleteGoogleAccount: (...args: unknown[]) => deleteGoogleAccount(...args),
  googleOAuthStart: (...args: unknown[]) => googleOAuthStart(...args),
  googleOAuthCallback: (...args: unknown[]) => googleOAuthCallback(...args),
  googleTest: (...args: unknown[]) => googleTest(...args),
  googleSync: (...args: unknown[]) => googleSync(...args),
  googleStatus: (...args: unknown[]) => googleStatus(...args),
  googleListCalendars: (...args: unknown[]) => googleListCalendars(...args),
  createGoogleCalendarEvent: (...args: unknown[]) => createGoogleCalendarEvent(...args),
  updateGoogleCalendarEvent: (...args: unknown[]) => updateGoogleCalendarEvent(...args),
  deleteGoogleCalendarEvent: (...args: unknown[]) => deleteGoogleCalendarEvent(...args)
}));

describe("GoogleConnectorPage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();

    listGoogleAccounts.mockResolvedValue([
      {
        id: "acc-1",
        tenant_id: "tenant-1",
        user_id: "user-1",
        label: "Work",
        google_account_email: "work@example.com",
        google_account_sub: "google-sub-1",
        is_oauth_connected: true,
        is_primary: true,
        scopes: [],
        gmail_enabled: true,
        gmail_labels: ["INBOX", "SENT"],
        calendar_enabled: true,
        calendar_ids: ["primary"],
        status: {
          enabled: true,
          last_sync_at: null,
          last_items_synced: 0,
          last_error: null
        }
      }
    ]);

    googleStatus.mockResolvedValue([]);
    googleListCalendars.mockResolvedValue([
      {
        id: "primary",
        summary: "Personal",
        primary: true,
        access_role: "owner",
        selected: true
      }
    ]);
    createGoogleAccount.mockResolvedValue({
      id: "acc-2",
      tenant_id: "tenant-1",
      user_id: "user-1",
      label: "Personal",
      google_account_email: null,
      google_account_sub: null,
      is_oauth_connected: false,
      is_primary: false,
      scopes: [],
      gmail_enabled: true,
      gmail_labels: ["INBOX", "SENT"],
      calendar_enabled: true,
      calendar_ids: ["primary"],
      status: {
        enabled: true,
        last_sync_at: null,
        last_items_synced: 0,
        last_error: null
      }
    });
    updateGoogleAccount.mockResolvedValue({});
    deleteGoogleAccount.mockResolvedValue({ message: "Google account disconnected", deleted_docs_count: 3 });
    googleOAuthStart.mockResolvedValue({ auth_url: "https://accounts.google.com/o/oauth2/v2/auth", state: "state-1" });
    googleOAuthCallback.mockResolvedValue({ message: "ok" });
    googleTest.mockResolvedValue({ message: "ok" });
    googleSync.mockResolvedValue({ message: "ok" });
    createGoogleCalendarEvent.mockResolvedValue({ id: "evt-1" });
    updateGoogleCalendarEvent.mockResolvedValue({ id: "evt-1" });
    deleteGoogleCalendarEvent.mockResolvedValue({ message: "deleted" });

    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("renders and loads account list", async () => {
    render(
      <MemoryRouter>
        <GoogleConnectorPage />
      </MemoryRouter>
    );

    expect(screen.getByText("My Google Accounts")).toBeInTheDocument();
    await waitFor(() => expect(listGoogleAccounts).toHaveBeenCalled());
    await waitFor(() => expect(googleStatus).toHaveBeenCalledWith("acc-1"));
    await waitFor(() => expect(googleListCalendars).toHaveBeenCalledWith("acc-1"));
    expect(screen.getByText("work@example.com")).toBeInTheDocument();
    expect(screen.getByText("Primary")).toBeInTheDocument();
  });

  it("creates a new account", async () => {
    render(
      <MemoryRouter>
        <GoogleConnectorPage />
      </MemoryRouter>
    );

    fireEvent.change(screen.getAllByPlaceholderText("Label (optional)")[0], { target: { value: "Personal" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Add Account" })[0]);

    await waitFor(() => {
      expect(createGoogleAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          label: "Personal",
          enabled: true,
          gmail_enabled: true,
          calendar_enabled: true
        })
      );
    });
  });

  it("saves and disconnects an account", async () => {
    render(
      <MemoryRouter>
        <GoogleConnectorPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(listGoogleAccounts).toHaveBeenCalled());

    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() => expect(updateGoogleAccount).toHaveBeenCalledWith("acc-1", expect.any(Object)));

    fireEvent.click(screen.getAllByRole("button", { name: "Disconnect" })[0]);
    await waitFor(() => expect(deleteGoogleAccount).toHaveBeenCalledWith("acc-1"));
  });

  it("disables Test and Sync for disconnected accounts", async () => {
    listGoogleAccounts.mockResolvedValueOnce([
      {
        id: "acc-3",
        tenant_id: "tenant-1",
        user_id: "user-1",
        label: "Unconnected",
        google_account_email: null,
        google_account_sub: null,
        is_oauth_connected: false,
        is_primary: false,
        scopes: [],
        gmail_enabled: true,
        gmail_labels: ["INBOX"],
        calendar_enabled: true,
        calendar_ids: ["primary"],
        status: {
          enabled: true,
          last_sync_at: null,
          last_items_synced: 0,
          last_error: null
        }
      }
    ]);

    render(
      <MemoryRouter>
        <GoogleConnectorPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(listGoogleAccounts).toHaveBeenCalled());
    const testButtons = screen.getAllByRole("button", { name: "Test" });
    const syncButtons = screen.getAllByRole("button", { name: "Sync" });
    expect(testButtons.at(-1)).toBeDisabled();
    expect(syncButtons.at(-1)).toBeDisabled();
  });

  it("sets a non-primary account as primary", async () => {
    listGoogleAccounts.mockResolvedValueOnce([
      {
        id: "acc-2",
        tenant_id: "tenant-1",
        user_id: "user-1",
        label: "Personal",
        google_account_email: "personal@example.com",
        google_account_sub: "google-sub-2",
        is_oauth_connected: true,
        is_primary: false,
        scopes: [],
        gmail_enabled: true,
        gmail_labels: ["INBOX"],
        calendar_enabled: true,
        calendar_ids: ["primary"],
        status: {
          enabled: true,
          last_sync_at: null,
          last_items_synced: 0,
          last_error: null
        }
      }
    ]);

    render(
      <MemoryRouter>
        <GoogleConnectorPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(listGoogleAccounts).toHaveBeenCalled());

    const buttons = screen.getAllByRole("button", { name: "Set as Primary" });
    const clickable = buttons.find((btn) => !btn.hasAttribute("disabled")) ?? buttons[buttons.length - 1];
    fireEvent.click(clickable);
    await waitFor(() => {
      expect(updateGoogleAccount).toHaveBeenCalledWith("acc-2", { is_primary: true });
    });
  });
});
