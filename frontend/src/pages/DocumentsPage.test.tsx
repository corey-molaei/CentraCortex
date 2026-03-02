import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { DocumentsPage } from "./DocumentsPage";

vi.mock("../api/documents", () => ({
  listDocuments: vi.fn().mockResolvedValue([
    {
      id: "doc-1",
      source_type: "file_upload",
      source_id: "notes.txt",
      title: "Notes",
      url: null,
      author: "file-upload",
      tags_json: [],
      acl_policy_id: null,
      current_chunk_version: 0,
      indexed_at: null,
      index_status: "failed",
      index_error: "embedding provider timeout",
      index_attempts: 3,
      index_requested_at: "2026-02-20T00:00:00Z",
      created_at: "2026-02-20T00:00:00Z",
      updated_at: "2026-02-20T00:00:00Z",
      chunk_count: 0
    }
  ]),
  reindexDocument: vi.fn(),
  reindexDocuments: vi.fn(),
  forgetDocument: vi.fn(),
  searchDocumentChunks: vi.fn().mockResolvedValue({ results: [] })
}));

describe("DocumentsPage", () => {
  it("renders index status and indexing error details", async () => {
    render(
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Notes")).toBeInTheDocument();
    });

    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("embedding provider timeout")).toBeInTheDocument();
  });
});
