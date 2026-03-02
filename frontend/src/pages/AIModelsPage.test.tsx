import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AIModelsPage } from "./AIModelsPage";

const llmApi = vi.hoisted(() => ({
  codexOAuthCallback: vi.fn(),
  codexOAuthStart: vi.fn(),
  createProvider: vi.fn(),
  deleteProvider: vi.fn(),
  disconnectCodexOAuth: vi.fn(),
  getCodexOAuthStatus: vi.fn(),
  listProviders: vi.fn(),
  testProvider: vi.fn(),
  updateProvider: vi.fn()
}));

vi.mock("../api/llm", () => llmApi);

const defaultProvider = {
  id: "provider-default",
  tenant_id: "tenant-1",
  name: "Default OpenAI",
  provider_type: "openai",
  base_url: "https://api.openai.com",
  model_name: "gpt-4.1-mini",
  is_default: true,
  is_fallback: false,
  rate_limit_rpm: 60,
  config_json: {},
  has_api_key: true,
  requires_oauth: false,
  oauth_connected: false,
  created_at: "2026-02-20T00:00:00Z"
} as const;

const nonDefaultProvider = {
  id: "provider-ollama",
  tenant_id: "tenant-1",
  name: "Ollama",
  provider_type: "ollama",
  base_url: "http://host.docker.internal:11434",
  model_name: "gemma3:4b",
  is_default: false,
  is_fallback: true,
  rate_limit_rpm: 120,
  config_json: {},
  has_api_key: false,
  requires_oauth: false,
  oauth_connected: false,
  created_at: "2026-02-20T00:00:00Z"
} as const;

describe("AIModelsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    llmApi.listProviders.mockResolvedValue([defaultProvider, nonDefaultProvider]);
    llmApi.getCodexOAuthStatus.mockResolvedValue({
      connected: false,
      connected_email: null,
      token_expires_at: null,
      scopes: []
    });
  });

  it("disables delete for default provider", async () => {
    render(
      <MemoryRouter>
        <AIModelsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Default OpenAI")).toBeInTheDocument();
    });

    const deleteButton = screen.getByTestId("provider-delete-provider-default");
    expect(deleteButton).toBeDisabled();
    expect(screen.getByText("Default provider: make another provider default before deleting.")).toBeInTheDocument();
  });

  it("deletes non-default provider and refreshes list", async () => {
    llmApi.listProviders
      .mockResolvedValueOnce([defaultProvider, nonDefaultProvider])
      .mockResolvedValueOnce([defaultProvider]);
    llmApi.deleteProvider.mockResolvedValue({ message: "Provider deleted" });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MemoryRouter>
        <AIModelsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByTestId("provider-delete-provider-ollama").length).toBeGreaterThan(0);
    });
    fireEvent.click(screen.getAllByTestId("provider-delete-provider-ollama")[0]);

    await waitFor(() => {
      expect(llmApi.deleteProvider).toHaveBeenCalledWith("provider-ollama");
    });
    await waitFor(() => {
      expect(screen.getByText("Provider deleted")).toBeInTheDocument();
    });
  });

  it("shows backend delete error details", async () => {
    llmApi.deleteProvider.mockRejectedValue(
      new Error("Default provider cannot be deleted. Assign another default first.")
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MemoryRouter>
        <AIModelsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByTestId("provider-delete-provider-ollama").length).toBeGreaterThan(0);
    });
    fireEvent.click(screen.getAllByTestId("provider-delete-provider-ollama")[0]);

    await waitFor(() => {
      expect(screen.getByText("Default provider cannot be deleted. Assign another default first.")).toBeInTheDocument();
    });
  });

  it("sets a provider as default", async () => {
    llmApi.listProviders
      .mockResolvedValueOnce([defaultProvider, nonDefaultProvider])
      .mockResolvedValueOnce([
        { ...defaultProvider, is_default: false },
        { ...nonDefaultProvider, is_default: true, is_fallback: false }
      ]);
    llmApi.updateProvider.mockResolvedValue({ ...nonDefaultProvider, is_default: true, is_fallback: false });

    render(
      <MemoryRouter>
        <AIModelsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByTestId("provider-set-default-provider-ollama").length).toBeGreaterThan(0);
    });
    fireEvent.click(screen.getAllByTestId("provider-set-default-provider-ollama")[0]);

    await waitFor(() => {
      expect(llmApi.updateProvider).toHaveBeenCalledWith("provider-ollama", { is_default: true });
    });
    await waitFor(() => {
      expect(screen.getByText("Ollama is now the default provider.")).toBeInTheDocument();
    });
  });

  it("edits an existing provider", async () => {
    llmApi.listProviders
      .mockResolvedValueOnce([defaultProvider, nonDefaultProvider])
      .mockResolvedValueOnce([defaultProvider, { ...nonDefaultProvider, name: "Ollama Edited" }]);
    llmApi.updateProvider.mockResolvedValue({ ...nonDefaultProvider, name: "Ollama Edited" });

    const { container } = render(
      <MemoryRouter>
        <AIModelsPage />
      </MemoryRouter>
    );
    const scope = within(container);

    await waitFor(() => {
      expect(scope.getAllByTestId("provider-edit-provider-ollama").length).toBeGreaterThan(0);
    });
    fireEvent.click(scope.getAllByTestId("provider-edit-provider-ollama")[0]);

    await waitFor(() => {
      expect(scope.getAllByText("Edit Provider").length).toBeGreaterThan(0);
    });
    fireEvent.change(scope.getAllByPlaceholderText("Provider name")[0], { target: { value: "Ollama Edited" } });
    fireEvent.click(scope.getAllByRole("button", { name: "Update Provider" })[0]);

    await waitFor(() => {
      expect(llmApi.updateProvider).toHaveBeenCalledWith("provider-ollama", {
        name: "Ollama Edited",
        base_url: "http://host.docker.internal:11434",
        api_key: undefined,
        model_name: "gemma3:4b",
        is_default: false,
        is_fallback: true,
        rate_limit_rpm: 120
      });
    });
    await waitFor(() => {
      expect(screen.getByText("Provider updated.")).toBeInTheDocument();
    });
  });

  it("hides API key input for codex provider", async () => {
    const { container } = render(
      <MemoryRouter>
        <AIModelsPage />
      </MemoryRouter>
    );
    const scope = within(container);

    await waitFor(() => {
      expect(scope.getAllByPlaceholderText("Provider name").length).toBeGreaterThan(0);
    });

    fireEvent.change(scope.getAllByDisplayValue("OpenAI")[0], { target: { value: "codex" } });
    expect(scope.queryByPlaceholderText("API key (optional for local providers)")).not.toBeInTheDocument();
    expect(scope.getByText("Codex providers use tenant OAuth login. Connect Codex above instead of API key.")).toBeInTheDocument();
  });
});
