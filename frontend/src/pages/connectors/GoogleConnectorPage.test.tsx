import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
const getGoogleSyncOptions = vi.fn();
const updateGoogleSyncOptions = vi.fn();
const googleListDriveFolders = vi.fn();
const googleListDriveFiles = vi.fn();
const googleListSpreadsheets = vi.fn();
const googleListSheetTabs = vi.fn();
const googleListContactGroups = vi.fn();
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
  getGoogleSyncOptions: (...args: unknown[]) => getGoogleSyncOptions(...args),
  updateGoogleSyncOptions: (...args: unknown[]) => updateGoogleSyncOptions(...args),
  googleListDriveFolders: (...args: unknown[]) => googleListDriveFolders(...args),
  googleListDriveFiles: (...args: unknown[]) => googleListDriveFiles(...args),
  googleListSpreadsheets: (...args: unknown[]) => googleListSpreadsheets(...args),
  googleListSheetTabs: (...args: unknown[]) => googleListSheetTabs(...args),
  googleListContactGroups: (...args: unknown[]) => googleListContactGroups(...args),
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
        drive_enabled: false,
        drive_folder_ids: [],
        drive_file_ids: [],
        sheets_enabled: false,
        sheets_targets: [],
        contacts_enabled: false,
        contacts_sync_mode: "all",
        contacts_group_ids: [],
        contacts_max_count: null,
        meet_enabled: true,
        crm_sheet_spreadsheet_id: null,
        crm_sheet_tab_name: null,
        sync_scope_configured: false,
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
    getGoogleSyncOptions.mockResolvedValue({
      gmail_sync_mode: "last_n_days",
      gmail_last_n_days: 30,
      gmail_max_messages: null,
      gmail_query: null,
      calendar_sync_mode: "range_days",
      calendar_days_back: 30,
      calendar_days_forward: 90,
      calendar_max_events: null,
      drive_enabled: false,
      drive_folder_ids: [],
      drive_file_ids: [],
      sheets_enabled: false,
      sheets_targets: [],
      contacts_enabled: false,
      contacts_sync_mode: "all",
      contacts_group_ids: [],
      contacts_max_count: null,
      sync_scope_configured: false
    });
    updateGoogleSyncOptions.mockResolvedValue({
      gmail_sync_mode: "last_n_days",
      gmail_last_n_days: 30,
      gmail_max_messages: null,
      gmail_query: null,
      calendar_sync_mode: "range_days",
      calendar_days_back: 30,
      calendar_days_forward: 90,
      calendar_max_events: null,
      drive_enabled: false,
      drive_folder_ids: [],
      drive_file_ids: [],
      sheets_enabled: false,
      sheets_targets: [],
      contacts_enabled: false,
      contacts_sync_mode: "all",
      contacts_group_ids: [],
      contacts_max_count: null,
      sync_scope_configured: true
    });
    googleListDriveFolders.mockResolvedValue([]);
    googleListDriveFiles.mockResolvedValue([]);
    googleListSpreadsheets.mockResolvedValue([]);
    googleListSheetTabs.mockResolvedValue([]);
    googleListContactGroups.mockResolvedValue([]);
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
      drive_enabled: false,
      drive_folder_ids: [],
      drive_file_ids: [],
      sheets_enabled: false,
      sheets_targets: [],
      contacts_enabled: false,
      contacts_sync_mode: "all",
      contacts_group_ids: [],
      contacts_max_count: null,
      meet_enabled: true,
      crm_sheet_spreadsheet_id: null,
      crm_sheet_tab_name: null,
      sync_scope_configured: false,
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

    const addSection = screen.getByText("Add Google Account").closest("section");
    expect(addSection).toBeTruthy();
    const scoped = within(addSection as HTMLElement);
    fireEvent.change(scoped.getByPlaceholderText("Label (optional)"), { target: { value: "Personal" } });
    fireEvent.change(scoped.getByPlaceholderText("Google account email (optional)"), { target: { value: "owner@example.com" } });
    fireEvent.click(scoped.getByLabelText("Drive"));
    fireEvent.click(scoped.getByLabelText("Sheets"));
    fireEvent.click(scoped.getByLabelText("Contacts"));
    fireEvent.click(screen.getAllByRole("button", { name: "Add Account" })[0]);

    await waitFor(() => {
      expect(createGoogleAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          label: "Personal",
          google_account_email: "owner@example.com",
          enabled: true,
          gmail_enabled: true,
          calendar_enabled: true,
          drive_enabled: true,
          sheets_enabled: true,
          contacts_enabled: true
        })
      );
    });
  });

  it("add and connect uses login hint from top email field", async () => {
    render(
      <MemoryRouter>
        <GoogleConnectorPage />
      </MemoryRouter>
    );

    const addSection = screen.getByText("Add Google Account").closest("section");
    expect(addSection).toBeTruthy();
    const scoped = within(addSection as HTMLElement);
    fireEvent.change(scoped.getByPlaceholderText("Label (optional)"), { target: { value: "Personal" } });
    fireEvent.change(scoped.getByPlaceholderText("Google account email (optional)"), { target: { value: "owner@example.com" } });
    fireEvent.click(scoped.getByRole("button", { name: "Add & Connect Google" }));

    await waitFor(() => {
      expect(googleOAuthStart).toHaveBeenCalledWith(
        "acc-2",
        `${window.location.origin}/connectors/google`,
        "owner@example.com"
      );
    });
  });

  it("reconnect auto-saves capability flags before starting oauth", async () => {
    render(
      <MemoryRouter>
        <GoogleConnectorPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(listGoogleAccounts).toHaveBeenCalled());
    const accountCard = screen.getByText("Work").closest("article");
    expect(accountCard).toBeTruthy();
    const scoped = within(accountCard as HTMLElement);

    fireEvent.click(scoped.getByLabelText("Drive"));
    fireEvent.click(scoped.getByLabelText("Sheets"));
    fireEvent.click(scoped.getByLabelText("Contacts"));
    fireEvent.click(scoped.getByRole("button", { name: "Reconnect" }));

    await waitFor(() => {
      expect(updateGoogleAccount).toHaveBeenCalledWith("acc-1", {
        gmail_enabled: true,
        calendar_enabled: true,
        drive_enabled: true,
        sheets_enabled: true,
        contacts_enabled: true
      });
    });
    await waitFor(() => {
      expect(googleOAuthStart).toHaveBeenCalledWith(
        "acc-1",
        `${window.location.origin}/connectors/google`,
        "work@example.com"
      );
    });

    const updateOrder = updateGoogleAccount.mock.invocationCallOrder.at(-1);
    const oauthOrder = googleOAuthStart.mock.invocationCallOrder.at(-1);
    expect(updateOrder).toBeDefined();
    expect(oauthOrder).toBeDefined();
    expect((updateOrder as number) < (oauthOrder as number)).toBe(true);
  });

  it("reconnect does not start oauth when capability save fails", async () => {
    updateGoogleAccount.mockRejectedValueOnce(new Error("save failed"));

    render(
      <MemoryRouter>
        <GoogleConnectorPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(listGoogleAccounts).toHaveBeenCalled());
    const accountCard = screen.getByText("Work").closest("article");
    expect(accountCard).toBeTruthy();
    const scoped = within(accountCard as HTMLElement);

    fireEvent.click(scoped.getByRole("button", { name: "Reconnect" }));

    await waitFor(() => {
      expect(updateGoogleAccount).toHaveBeenCalledWith("acc-1", {
        gmail_enabled: true,
        calendar_enabled: true,
        drive_enabled: false,
        sheets_enabled: false,
        contacts_enabled: false
      });
    });
    await waitFor(() => {
      expect(googleOAuthStart).not.toHaveBeenCalled();
    });
    expect(await screen.findByText("save failed")).toBeInTheDocument();
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
        drive_enabled: false,
        drive_folder_ids: [],
        drive_file_ids: [],
        sheets_enabled: false,
        sheets_targets: [],
        contacts_enabled: false,
        contacts_sync_mode: "all",
        contacts_group_ids: [],
        contacts_max_count: null,
        meet_enabled: true,
        crm_sheet_spreadsheet_id: null,
        crm_sheet_tab_name: null,
        sync_scope_configured: false,
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
        drive_enabled: false,
        drive_folder_ids: [],
        drive_file_ids: [],
        sheets_enabled: false,
        sheets_targets: [],
        contacts_enabled: false,
        contacts_sync_mode: "all",
        contacts_group_ids: [],
        contacts_max_count: null,
        meet_enabled: true,
        crm_sheet_spreadsheet_id: null,
        crm_sheet_tab_name: null,
        sync_scope_configured: false,
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
