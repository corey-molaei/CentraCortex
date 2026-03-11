import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FileUploadConnectorPage } from "./FileUploadConnectorPage";

const connectorApi = vi.hoisted(() => ({
  connectorStatus: vi.fn(),
  getConnectorConfig: vi.fn(),
  putConnectorConfig: vi.fn(),
  testConnector: vi.fn(),
  uploadFiles: vi.fn()
}));

vi.mock("../../api/connectors", () => connectorApi);

describe("FileUploadConnectorPage", () => {
  it("shows validation error when uploading without selecting files", async () => {
    connectorApi.getConnectorConfig.mockResolvedValue({
      allowed_extensions: ["txt", "pdf", "docx", "xls", "xlsx", "doc"],
      status: {
        enabled: true,
        last_sync_at: null,
        last_items_synced: 0,
        last_error: null
      }
    });
    connectorApi.connectorStatus.mockResolvedValue([]);

    render(<FileUploadConnectorPage />);

    await waitFor(() => {
      expect(screen.getByText("File Upload Connector Wizard")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Upload and Ingest" }));

    expect(screen.getByText("Choose at least one file before uploading.")).toBeInTheDocument();
  });
});
