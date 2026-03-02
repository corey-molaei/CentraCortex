import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EmailConnectorPage } from "./EmailConnectorPage";

const listEmailAccounts = vi.fn();
const createEmailAccount = vi.fn();
const updateEmailAccount = vi.fn();
const deleteEmailAccount = vi.fn();
const testEmailAccount = vi.fn();
const syncEmailAccount = vi.fn();
const emailAccountStatus = vi.fn();

vi.mock("../../api/connectors", () => ({
  listEmailAccounts: (...args: unknown[]) => listEmailAccounts(...args),
  createEmailAccount: (...args: unknown[]) => createEmailAccount(...args),
  updateEmailAccount: (...args: unknown[]) => updateEmailAccount(...args),
  deleteEmailAccount: (...args: unknown[]) => deleteEmailAccount(...args),
  testEmailAccount: (...args: unknown[]) => testEmailAccount(...args),
  syncEmailAccount: (...args: unknown[]) => syncEmailAccount(...args),
  emailAccountStatus: (...args: unknown[]) => emailAccountStatus(...args)
}));

describe("EmailConnectorPage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    listEmailAccounts.mockResolvedValue([
      {
        id: "acc-1",
        tenant_id: "tenant-1",
        user_id: "user-1",
        label: "Work",
        email_address: "work@example.com",
        username: "work@example.com",
        imap_host: "imap.example.com",
        imap_port: 993,
        use_ssl: true,
        smtp_host: "smtp.example.com",
        smtp_port: 587,
        smtp_use_starttls: true,
        folders: ["INBOX"],
        is_primary: true,
        status: {
          enabled: true,
          last_sync_at: null,
          last_items_synced: 0,
          last_error: null
        }
      }
    ]);
    emailAccountStatus.mockResolvedValue([]);
    createEmailAccount.mockResolvedValue({ id: "acc-2" });
    updateEmailAccount.mockResolvedValue({});
    deleteEmailAccount.mockResolvedValue({ message: "Email account disconnected", deleted_docs_count: 0 });
    testEmailAccount.mockResolvedValue({ success: true, message: "ok" });
    syncEmailAccount.mockResolvedValue({ status: "success", items_synced: 1, message: "ok" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("renders and loads account list", async () => {
    render(
      <MemoryRouter>
        <EmailConnectorPage />
      </MemoryRouter>
    );
    expect(screen.getByText("My Email Accounts")).toBeInTheDocument();
    await waitFor(() => expect(listEmailAccounts).toHaveBeenCalled());
    expect(screen.getByText("work@example.com")).toBeInTheDocument();
  });

  it("creates a new email account", async () => {
    render(
      <MemoryRouter>
        <EmailConnectorPage />
      </MemoryRouter>
    );
    fireEvent.change(screen.getByPlaceholderText("Email address"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Username"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Password / App Password"), { target: { value: "secret" } });
    fireEvent.change(screen.getByPlaceholderText("IMAP host"), { target: { value: "imap.example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Account" }));

    await waitFor(() => {
      expect(createEmailAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          email_address: "new@example.com",
          username: "new@example.com"
        })
      );
    });
  });

  it("saves and deletes an account", async () => {
    render(
      <MemoryRouter>
        <EmailConnectorPage />
      </MemoryRouter>
    );
    await waitFor(() => expect(listEmailAccounts).toHaveBeenCalled());

    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() => expect(updateEmailAccount).toHaveBeenCalledWith("acc-1", expect.any(Object)));

    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    await waitFor(() => expect(deleteEmailAccount).toHaveBeenCalledWith("acc-1"));
  });
});
