import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPage } from "./ChatPage";

const llmApi = vi.hoisted(() => ({
  completeChat: vi.fn(),
  confirmChatAction: vi.fn(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
  listConversations: vi.fn(),
  listProviders: vi.fn(),
  reportAnswer: vi.fn(),
  selectChatAction: vi.fn()
}));

vi.mock("../api/llm", () => llmApi);

const conversationA = {
  id: "conv-a",
  title: "Conversation A",
  created_at: "2026-02-20T10:00:00Z",
  updated_at: "2026-02-20T10:00:00Z",
  last_message_at: "2026-02-20T10:00:00Z"
};

const conversationB = {
  id: "conv-b",
  title: "Conversation B",
  created_at: "2026-02-20T11:00:00Z",
  updated_at: "2026-02-20T11:00:00Z",
  last_message_at: "2026-02-20T11:00:00Z"
};

const detailA = {
  ...conversationA,
  messages: [
    {
      id: "msg-user-a",
      role: "user",
      content: "Hello from A",
      created_at: "2026-02-20T10:00:00Z",
      citations: [],
      safety_flags: [],
      provider_name: null,
      model_name: null
    },
    {
      id: "msg-assistant-a",
      role: "assistant",
      content: "Assistant response A",
      created_at: "2026-02-20T10:00:10Z",
      citations: [],
      safety_flags: [],
      provider_name: "Test Provider",
      model_name: "test-model"
    }
  ]
};

const detailB = {
  ...conversationB,
  messages: [
    {
      id: "msg-user-b",
      role: "user",
      content: "Hello from B",
      created_at: "2026-02-20T11:00:00Z",
      citations: [],
      safety_flags: [],
      provider_name: null,
      model_name: null
    },
    {
      id: "msg-assistant-b",
      role: "assistant",
      content: "Assistant response B",
      created_at: "2026-02-20T11:00:10Z",
      citations: [],
      safety_flags: [],
      provider_name: "Test Provider",
      model_name: "test-model"
    }
  ]
};

describe("ChatPage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
    llmApi.listProviders.mockResolvedValue([]);
    llmApi.listConversations.mockResolvedValue([conversationA, conversationB]);
    llmApi.getConversation.mockResolvedValue(detailA);
    llmApi.deleteConversation.mockResolvedValue({ message: "Conversation deleted" });
    llmApi.confirmChatAction.mockResolvedValue({
      conversation_id: "conv-a",
      assistant_message_id: "assistant-confirm",
      provider_id: "email-action",
      provider_name: "Email Action Engine",
      model_name: "email-action",
      answer: "Cancelled.",
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      cost_usd: 0,
      blocked: false,
      safety_flags: [],
      citations: [],
      interaction_type: "execution_result",
      action_context: null,
      options: []
    });
    llmApi.selectChatAction.mockResolvedValue({
      conversation_id: "conv-a",
      assistant_message_id: "assistant-select",
      provider_id: "calendar-action",
      provider_name: "Calendar Action Engine",
      model_name: "calendar-action",
      answer: "Selected.",
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      cost_usd: 0,
      blocked: false,
      safety_flags: [],
      citations: [],
      interaction_type: "execution_result",
      action_context: null,
      options: []
    });
  });

  it("starts a blank draft when New is clicked and does not reselect old conversation", async () => {
    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(llmApi.getConversation).toHaveBeenCalledWith("conv-a");
    });
    expect(screen.getByText("Assistant response A")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "New" }));

    expect(screen.getByText("No messages yet.")).toBeInTheDocument();
    await waitFor(() => {
      expect(llmApi.getConversation).toHaveBeenCalledTimes(1);
    });
  });

  it("sends client timezone with chat requests", async () => {
    llmApi.completeChat.mockResolvedValue({
      conversation_id: "conv-a",
      assistant_message_id: "assistant-1",
      provider_id: "provider-1",
      provider_name: "Test Provider",
      model_name: "test-model",
      answer: "ok",
      prompt_tokens: 1,
      completion_tokens: 1,
      total_tokens: 2,
      cost_usd: 0.0,
      blocked: false,
      safety_flags: [],
      citations: []
    });
    llmApi.getConversation.mockResolvedValue(detailA);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(llmApi.getConversation).toHaveBeenCalledWith("conv-a");
    });

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "add a meeting tomorrow 2pm" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(llmApi.completeChat).toHaveBeenCalledWith(
        expect.objectContaining({
          client_timezone: expect.any(String)
        })
      );
    });
  });

  it("submits chat on Enter and keeps newline behavior on Shift+Enter", async () => {
    llmApi.completeChat.mockResolvedValue({
      conversation_id: "conv-a",
      assistant_message_id: "assistant-enter",
      provider_id: "provider-1",
      provider_name: "Test Provider",
      model_name: "test-model",
      answer: "ok",
      prompt_tokens: 1,
      completion_tokens: 1,
      total_tokens: 2,
      cost_usd: 0.0,
      blocked: false,
      safety_flags: [],
      citations: []
    });
    llmApi.getConversation.mockResolvedValue(detailA);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(llmApi.getConversation).toHaveBeenCalledWith("conv-a");
    });

    const promptBox = screen.getByRole("textbox");
    fireEvent.change(promptBox, { target: { value: "send via enter" } });
    fireEvent.keyDown(promptBox, { key: "Enter", code: "Enter", charCode: 13 });

    await waitFor(() => {
      expect(llmApi.completeChat).toHaveBeenCalledTimes(1);
    });

    fireEvent.change(promptBox, { target: { value: "shift enter no send" } });
    fireEvent.keyDown(promptBox, { key: "Enter", code: "Enter", charCode: 13, shiftKey: true });

    await waitFor(() => {
      expect(llmApi.completeChat).toHaveBeenCalledTimes(1);
    });
  });

  it("shows user message immediately while assistant response is pending", async () => {
    let resolveChat: (value: unknown) => void = () => {};
    const pendingChat = new Promise<unknown>((resolve) => {
      resolveChat = resolve;
    });
    llmApi.listConversations.mockResolvedValueOnce([]).mockResolvedValueOnce([conversationA]);
    llmApi.getConversation.mockResolvedValue({
      ...conversationA,
      messages: [
        {
          id: "msg-user-pending",
          role: "user",
          content: "first question",
          created_at: "2026-02-20T12:00:00Z",
          citations: [],
          safety_flags: [],
          provider_name: null,
          model_name: null
        },
        {
          id: "msg-assistant-pending",
          role: "assistant",
          content: "final answer",
          created_at: "2026-02-20T12:00:05Z",
          citations: [],
          safety_flags: [],
          provider_name: "Test Provider",
          model_name: "test-model"
        }
      ]
    });
    llmApi.completeChat.mockReturnValue(pendingChat);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("No messages yet.")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "first question" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(screen.getByText("first question")).toBeInTheDocument();
    expect(screen.queryByText("final answer")).not.toBeInTheDocument();

    resolveChat({
      conversation_id: "conv-a",
      assistant_message_id: "assistant-pending",
      provider_id: "provider-1",
      provider_name: "Test Provider",
      model_name: "test-model",
      answer: "final answer",
      prompt_tokens: 1,
      completion_tokens: 1,
      total_tokens: 2,
      cost_usd: 0.0,
      blocked: false,
      safety_flags: [],
      citations: []
    });

    await waitFor(() => {
      expect(screen.getByText("final answer")).toBeInTheDocument();
    });
  });

  it("deletes an active conversation and loads the next available one", async () => {
    llmApi.listConversations.mockResolvedValueOnce([conversationA, conversationB]).mockResolvedValueOnce([conversationB]);
    llmApi.getConversation.mockResolvedValueOnce(detailA).mockResolvedValueOnce(detailB);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Assistant response A")).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByTestId("conversation-delete-conv-a")[0]);

    await waitFor(() => {
      expect(llmApi.deleteConversation).toHaveBeenCalledWith("conv-a");
    });
    await waitFor(() => {
      expect(llmApi.getConversation).toHaveBeenCalledWith("conv-b");
    });
    expect(screen.getByText("Conversation deleted")).toBeInTheDocument();
  });

  it("clears stale citation snippets when a newer response has no citations", async () => {
    const citationSnippet = "Michael Bradoo profile excerpt";
    const detailWithCitation = {
      ...conversationA,
      messages: [
        {
          id: "msg-user-a",
          role: "user",
          content: "Who is Michael Bradoo?",
          created_at: "2026-02-20T10:00:00Z",
          citations: [],
          safety_flags: [],
          provider_name: null,
          model_name: null
        },
        {
          id: "msg-assistant-a",
          role: "assistant",
          content: "I found a reference.",
          created_at: "2026-02-20T10:00:10Z",
          citations: [
            {
              document_id: "doc-1",
              document_title: "Profile",
              document_url: null,
              source_type: "manual",
              chunk_id: "chunk-1",
              chunk_index: 0,
              snippet: citationSnippet
            }
          ],
          safety_flags: [],
          provider_name: "Test Provider",
          model_name: "test-model"
        }
      ]
    };

    const detailWithoutCitation = {
      ...conversationA,
      messages: [
        {
          id: "msg-user-a2",
          role: "user",
          content: "Unknown person query",
          created_at: "2026-02-20T10:01:00Z",
          citations: [],
          safety_flags: [],
          provider_name: null,
          model_name: null
        },
        {
          id: "msg-assistant-a2",
          role: "assistant",
          content: "No relevant information found.",
          created_at: "2026-02-20T10:01:10Z",
          citations: [],
          safety_flags: [],
          provider_name: "Test Provider",
          model_name: "test-model"
        }
      ]
    };

    llmApi.listConversations.mockResolvedValue([conversationA]);
    llmApi.getConversation
      .mockResolvedValueOnce(detailA)
      .mockResolvedValueOnce(detailWithCitation)
      .mockResolvedValueOnce(detailWithoutCitation);

    llmApi.completeChat
      .mockResolvedValueOnce({
        conversation_id: "conv-a",
        assistant_message_id: "assistant-1",
        provider_id: "provider-1",
        provider_name: "Test Provider",
        model_name: "test-model",
        answer: "I found a reference.",
        prompt_tokens: 3,
        completion_tokens: 3,
        total_tokens: 6,
        cost_usd: 0.001,
        blocked: false,
        safety_flags: [],
        citations: [
          {
            document_id: "doc-1",
            document_title: "Profile",
            document_url: null,
            source_type: "manual",
            chunk_id: "chunk-1",
            chunk_index: 0,
            snippet: citationSnippet
          }
        ]
      })
      .mockResolvedValueOnce({
        conversation_id: "conv-a",
        assistant_message_id: "assistant-2",
        provider_id: "provider-1",
        provider_name: "Test Provider",
        model_name: "test-model",
        answer: "No relevant information found.",
        prompt_tokens: 2,
        completion_tokens: 2,
        total_tokens: 4,
        cost_usd: 0.001,
        blocked: false,
        safety_flags: [],
        citations: []
      });

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(llmApi.getConversation).toHaveBeenCalledWith("conv-a");
    });

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Who is Michael Bradoo?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText(citationSnippet)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Unknown person query" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText("No citations for current response.")).toBeInTheDocument();
    });
    expect(screen.queryByText(citationSnippet)).not.toBeInTheDocument();
  });

  it("shows error message when delete request fails", async () => {
    llmApi.listConversations.mockResolvedValueOnce([conversationA]);
    llmApi.getConversation.mockResolvedValueOnce(detailA);
    llmApi.deleteConversation.mockRejectedValue(new Error("Delete failed"));
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Assistant response A")).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByTestId("conversation-delete-conv-a")[0]);

    await waitFor(() => {
      expect(screen.getByText("Delete failed")).toBeInTheDocument();
    });
  });

  it("renders confirmation controls and calls confirm action endpoint", async () => {
    llmApi.completeChat.mockResolvedValue({
      conversation_id: "conv-a",
      assistant_message_id: "assistant-confirm-needed",
      provider_id: "email-action",
      provider_name: "Email Action Engine",
      model_name: "email-action",
      answer: "Please confirm sending this email (yes/no)",
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      cost_usd: 0,
      blocked: false,
      safety_flags: [],
      citations: [],
      interaction_type: "confirmation_required",
      action_context: { action_type: "email_send" },
      options: [
        { id: "yes", label: "Confirm" },
        { id: "no", label: "Cancel" }
      ]
    });

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(llmApi.getConversation).toHaveBeenCalledWith("conv-a");
    });

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "send email to a@b.com hi" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText("Confirmation required")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => {
      expect(llmApi.confirmChatAction).toHaveBeenCalledWith(
        expect.objectContaining({
          conversation_id: "conv-a",
          confirm: true
        })
      );
    });
  });

  it("shows pinned model state and disables provider override for pinned conversation", async () => {
    llmApi.listProviders.mockResolvedValue([
      {
        id: "provider-4b",
        tenant_id: "tenant-1",
        name: "google",
        provider_type: "ollama",
        base_url: "http://localhost:11434",
        model_name: "gemma3:4b",
        is_default: false,
        is_fallback: false,
        rate_limit_rpm: 60,
        config_json: {},
        has_api_key: false,
        requires_oauth: false,
        oauth_connected: false,
        created_at: "2026-02-20T10:00:00Z"
      }
    ]);
    const pinnedConversation = {
      ...conversationA,
      pinned_provider_id: "provider-4b",
      pinned_provider_name: "google",
      pinned_model_name: "gemma3:4b",
      pinned_at: "2026-02-20T10:00:00Z"
    };
    llmApi.listConversations.mockResolvedValueOnce([pinnedConversation]);
    llmApi.getConversation.mockResolvedValueOnce({
      ...detailA,
      pinned_provider_id: "provider-4b",
      pinned_provider_name: "google",
      pinned_model_name: "gemma3:4b",
      pinned_at: "2026-02-20T10:00:00Z"
    });

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Pinned model for this conversation: google / gemma3:4b")).toBeInTheDocument();
    });

    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(
      screen.getByText("This conversation is pinned to google / gemma3:4b. Start a new conversation to switch.")
    ).toBeInTheDocument();
  });

  it("shows start-new CTA when pinned provider is unavailable", async () => {
    llmApi.completeChat.mockRejectedValue(
      new Error("This conversation is pinned to a provider that is unavailable. Choose a provider and start a new conversation.")
    );

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(llmApi.getConversation).toHaveBeenCalledWith("conv-a");
    });

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "test request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText(/pinned to a provider that is unavailable/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Start New Conversation" }));
    expect(screen.getByText("No messages yet.")).toBeInTheDocument();
  });
});
