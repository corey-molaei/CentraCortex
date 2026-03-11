import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  completeChat,
  confirmChatAction,
  deleteConversation,
  getConversation,
  listConversations,
  listProviders,
  reportAnswer,
  selectChatAction
} from "../api/llm";
import type { ChatActionOption, Citation, ConversationMessage, ConversationSummary, LLMProvider } from "../types/llm";

const CHAT_PROVIDER_OVERRIDE_KEY = "chat_provider_override";
const CONVERSATION_PAGE_SIZE = 8;

export function ChatPage() {
  const messagesContainerRef = useRef<HTMLDivElement | null>(null);
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [providerOverride, setProviderOverride] = useState("");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [prompt, setPrompt] = useState("Give me a summary of this week's top risks.");
  const [latestCitations, setLatestCitations] = useState<Citation[]>([]);
  const [lastAssistantMessageId, setLastAssistantMessageId] = useState<string | null>(null);
  const [modelIndicator, setModelIndicator] = useState<string>("Not set");
  const [showSources, setShowSources] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingInteractionType, setPendingInteractionType] = useState<"confirmation_required" | "selection_required" | null>(
    null
  );
  const [pendingOptions, setPendingOptions] = useState<ChatActionOption[]>([]);
  const [sending, setSending] = useState(false);
  const [deletingConversationId, setDeletingConversationId] = useState<string | null>(null);
  const [conversationsOpen, setConversationsOpen] = useState(true);
  const [loadingConversationList, setLoadingConversationList] = useState(false);
  const [loadingMoreConversations, setLoadingMoreConversations] = useState(false);
  const [conversationOffset, setConversationOffset] = useState(0);
  const [hasMoreConversations, setHasMoreConversations] = useState(false);
  const [activePinnedProviderId, setActivePinnedProviderId] = useState<string | null>(null);
  const [activePinnedModelLabel, setActivePinnedModelLabel] = useState<string | null>(null);
  const clientTimezone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    []
  );
  const defaultProvider = useMemo(
    () => providers.find((provider) => provider.is_default) ?? providers[0] ?? null,
    [providers]
  );
  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === providerOverride) ?? null,
    [providers, providerOverride]
  );
  const nextModelLabel = useMemo(() => {
    if (activePinnedModelLabel) {
      return `${activePinnedModelLabel} (conversation pinned)`;
    }
    if (selectedProvider) {
      return `${selectedProvider.name} / ${selectedProvider.model_name}`;
    }
    if (defaultProvider) {
      return `${defaultProvider.name} / ${defaultProvider.model_name} (tenant default)`;
    }
    return "No provider configured";
  }, [activePinnedModelLabel, defaultProvider, selectedProvider]);

  const clearConversationState = useCallback(() => {
    setActiveConversationId(null);
    setActivePinnedProviderId(null);
    setActivePinnedModelLabel(null);
    setMessages([]);
    setLatestCitations([]);
    setLastAssistantMessageId(null);
    setPendingInteractionType(null);
    setPendingOptions([]);
  }, []);

  const loadConversationDetail = useCallback(async (conversationId: string) => {
    const detail = await getConversation(conversationId);
    setMessages(detail.messages);
    setActivePinnedProviderId(detail.pinned_provider_id ?? null);
    setActivePinnedModelLabel(
      detail.pinned_provider_name && detail.pinned_model_name
        ? `${detail.pinned_provider_name} / ${detail.pinned_model_name}`
        : null
    );
    const lastAssistant = [...detail.messages].reverse().find((m) => m.role === "assistant");
    setLatestCitations(lastAssistant?.citations ?? []);
    setLastAssistantMessageId(lastAssistant?.id ?? null);
    if (lastAssistant?.provider_name && lastAssistant?.model_name) {
      setModelIndicator(`${lastAssistant.provider_name} / ${lastAssistant.model_name}`);
    }
  }, []);

  const refreshConversations = useCallback(async (selectedConversationId?: string | null) => {
    setLoadingConversationList(true);
    try {
      const list = await listConversations({ limit: CONVERSATION_PAGE_SIZE, offset: 0 });
      setConversations(list);
      setConversationOffset(list.length);
      setHasMoreConversations(list.length === CONVERSATION_PAGE_SIZE);

      if (selectedConversationId === null) {
        clearConversationState();
        return;
      }

      const target = selectedConversationId ?? list[0]?.id ?? null;
      setActiveConversationId(target);
      if (target) {
        await loadConversationDetail(target);
      } else {
        clearConversationState();
      }
    } finally {
      setLoadingConversationList(false);
    }
  }, [clearConversationState, loadConversationDetail]);

  const loadMoreConversations = useCallback(async () => {
    if (loadingMoreConversations || !hasMoreConversations) {
      return;
    }
    setLoadingMoreConversations(true);
    try {
      const nextPage = await listConversations({
        limit: CONVERSATION_PAGE_SIZE,
        offset: conversationOffset,
      });
      setConversations((prev) => {
        const existing = new Set(prev.map((item) => item.id));
        return [...prev, ...nextPage.filter((item) => !existing.has(item.id))];
      });
      setConversationOffset((prev) => prev + nextPage.length);
      setHasMoreConversations(nextPage.length === CONVERSATION_PAGE_SIZE);
    } finally {
      setLoadingMoreConversations(false);
    }
  }, [conversationOffset, hasMoreConversations, loadingMoreConversations]);

  const startNewConversation = useCallback(() => {
    setStatusMessage(null);
    setError(null);
    clearConversationState();
    setConversationsOpen(false);
  }, [clearConversationState]);

  useEffect(() => {
    Promise.all([listProviders(), refreshConversations(undefined)])
      .then(([providersData]) => {
        setProviders(providersData);
        const persistedOverride = window.localStorage.getItem(CHAT_PROVIDER_OVERRIDE_KEY);
        const persistedExists = providersData.some((provider) => provider.id === persistedOverride);
        const initialOverride = persistedExists
          ? (persistedOverride ?? "")
          : (providersData.find((provider) => provider.is_default)?.id ?? "");
        setProviderOverride(initialOverride);
        if (initialOverride) {
          const provider = providersData.find((item) => item.id === initialOverride);
          if (provider) {
            setModelIndicator(`${provider.name} / ${provider.model_name}`);
          }
        } else {
          setModelIndicator("Not set");
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to initialize chat"));
  }, [refreshConversations]);

  const groupedMessages = useMemo(
    () => messages.filter((m) => m.role === "user" || m.role === "assistant"),
    [messages]
  );

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [groupedMessages]);

  async function submitPrompt() {
    if (sending) {
      return;
    }
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) {
      return;
    }
    const optimisticUserMessageId = `optimistic-user-${Date.now()}`;
    const optimisticUserMessage: ConversationMessage = {
      id: optimisticUserMessageId,
      role: "user",
      content: trimmedPrompt,
      created_at: new Date().toISOString(),
      citations: [],
      safety_flags: [],
      provider_name: null,
      model_name: null,
    };
    setMessages((prev) => [...prev, optimisticUserMessage]);
    setPrompt("");
    setLatestCitations([]);
    setLastAssistantMessageId(null);
    setSending(true);
    setError(null);
    setStatusMessage(null);
    try {
      const response = await completeChat({
        messages: [{ role: "user", content: trimmedPrompt }],
        provider_id_override: (activePinnedProviderId ?? providerOverride) || undefined,
        conversation_id: activeConversationId ?? undefined,
        retrieval_limit: 8,
        client_timezone: clientTimezone,
        client_now_iso: new Date().toISOString()
      });
      setModelIndicator(`${response.provider_name} / ${response.model_name}`);
      setLatestCitations(response.citations);
      setLastAssistantMessageId(response.assistant_message_id);
      if (response.blocked) {
        setStatusMessage(`Blocked by safety guard: ${response.safety_flags.join(", ")}`);
      } else if (response.safety_flags.length > 0) {
        setStatusMessage(`Safety flags: ${response.safety_flags.join(", ")}`);
      }
      await refreshConversations(response.conversation_id);
      setPendingInteractionType(
        response.interaction_type === "confirmation_required" || response.interaction_type === "selection_required"
          ? response.interaction_type
          : null
      );
      setPendingOptions(response.options ?? []);
    } catch (err) {
      setMessages((prev) => prev.filter((message) => message.id !== optimisticUserMessageId));
      setPrompt(trimmedPrompt);
      setError(err instanceof Error ? err.message : "Chat request failed");
    } finally {
      setSending(false);
    }
  }

  async function confirmPendingAction(confirm: boolean) {
    if (!activeConversationId || sending) {
      return;
    }
    setSending(true);
    setError(null);
    setStatusMessage(null);
    try {
      const response = await confirmChatAction({
        conversation_id: activeConversationId,
        confirm,
        provider_id_override: (activePinnedProviderId ?? providerOverride) || undefined,
        retrieval_limit: 8,
        client_timezone: clientTimezone,
        client_now_iso: new Date().toISOString()
      });
      setModelIndicator(`${response.provider_name} / ${response.model_name}`);
      setLatestCitations(response.citations);
      setLastAssistantMessageId(response.assistant_message_id);
      await refreshConversations(response.conversation_id);
      setPendingInteractionType(
        response.interaction_type === "confirmation_required" || response.interaction_type === "selection_required"
          ? response.interaction_type
          : null
      );
      setPendingOptions(response.options ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to confirm action");
    } finally {
      setSending(false);
    }
  }

  async function selectPendingAction(selection: string) {
    if (!activeConversationId || sending) {
      return;
    }
    setSending(true);
    setError(null);
    setStatusMessage(null);
    try {
      const response = await selectChatAction({
        conversation_id: activeConversationId,
        selection,
        provider_id_override: (activePinnedProviderId ?? providerOverride) || undefined,
        retrieval_limit: 8,
        client_timezone: clientTimezone,
        client_now_iso: new Date().toISOString()
      });
      setModelIndicator(`${response.provider_name} / ${response.model_name}`);
      setLatestCitations(response.citations);
      setLastAssistantMessageId(response.assistant_message_id);
      await refreshConversations(response.conversation_id);
      setPendingInteractionType(
        response.interaction_type === "confirmation_required" || response.interaction_type === "selection_required"
          ? response.interaction_type
          : null
      );
      setPendingOptions(response.options ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to select action option");
    } finally {
      setSending(false);
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    await submitPrompt();
  }

  function onPromptKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }
    event.preventDefault();
    void submitPrompt();
  }

  async function onDeleteConversation(conversation: ConversationSummary) {
    if (!window.confirm("Delete this conversation? This action cannot be undone.")) {
      return;
    }

    setError(null);
    setStatusMessage(null);
    setDeletingConversationId(conversation.id);
    try {
      const result = await deleteConversation(conversation.id);
      setStatusMessage(result.message);
      setPendingInteractionType(null);
      setPendingOptions([]);
      const nextSelection = activeConversationId === conversation.id ? undefined : activeConversationId;
      await refreshConversations(nextSelection);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete conversation");
    } finally {
      setDeletingConversationId(null);
    }
  }

  const renderConversationsList = () => (
    <div className="flex h-full min-h-[320px] flex-col">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Conversations</h2>
        <span className="text-xs text-slate-400">Recent first</span>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto pr-1">
        {conversations.map((conv) => (
          <div
            className={`flex items-start gap-2 rounded border p-2 ${
              conv.id === activeConversationId ? "border-accent bg-slate-900" : "border-slate-700"
            }`}
            key={conv.id}
          >
            <button
              className="flex-1 text-left text-sm"
              data-testid={`conversation-select-${conv.id}`}
              onClick={async () => {
                setPendingInteractionType(null);
                setPendingOptions([]);
                setError(null);
                setStatusMessage(null);
                setActiveConversationId(conv.id);
                await loadConversationDetail(conv.id);
                setConversationsOpen(false);
              }}
              type="button"
            >
              <div className="font-medium">{conv.title}</div>
              <div className="text-xs text-slate-400">{new Date(conv.last_message_at).toLocaleString()}</div>
            </button>
            <button
              className="shrink-0 rounded border border-red-500/60 px-3 py-2 text-xs text-red-300 disabled:opacity-50"
              data-testid={`conversation-delete-${conv.id}`}
              disabled={deletingConversationId === conv.id}
              onClick={() => onDeleteConversation(conv)}
              type="button"
            >
              {deletingConversationId === conv.id ? "Deleting..." : "Delete"}
            </button>
          </div>
        ))}
        {!loadingConversationList && conversations.length === 0 && <p className="text-sm text-slate-400">No conversations yet.</p>}
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        {loadingConversationList && <p className="text-xs text-slate-400">Loading conversations...</p>}
        {!loadingConversationList && hasMoreConversations && (
          <button
            className="rounded border border-slate-700 px-3 py-1.5 text-xs disabled:opacity-50"
            data-testid="conversations-show-more"
            disabled={loadingMoreConversations}
            onClick={() => {
              void loadMoreConversations();
            }}
            type="button"
          >
            {loadingMoreConversations ? "Loading..." : "Show more"}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <main className="mx-auto max-w-[1400px] p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Chat Workspace</h1>
        <div className="flex items-center gap-3">
          <button
            className="rounded border border-slate-700 px-4 py-2 text-sm font-medium"
            onClick={startNewConversation}
            type="button"
          >
            New
          </button>
          <button
            className="rounded border border-slate-700 px-3 py-2 text-sm lg:hidden"
            onClick={() => setConversationsOpen((value) => !value)}
            type="button"
          >
            {conversationsOpen ? "Close Conversations" : "Conversations"}
          </button>
          <Link className="text-sm text-accent underline" to="/">
            Back to dashboard
          </Link>
        </div>
      </header>

      {error && (
        <div className="mb-4 rounded bg-red-500/15 p-3 text-red-200">
          <div>{error}</div>
          {error.includes("pinned to a provider that is unavailable") && (
            <button
              className="mt-2 rounded border border-red-300 px-3 py-1 text-sm text-red-100"
              onClick={startNewConversation}
              type="button"
            >
              Start New Conversation
            </button>
          )}
        </div>
      )}
      {statusMessage && <div className="mb-4 rounded bg-amber-500/15 p-3 text-amber-200">{statusMessage}</div>}

      {conversationsOpen && (
        <button
          aria-label="Close conversations drawer"
          className="fixed inset-0 z-20 bg-black/60 lg:hidden"
          onClick={() => setConversationsOpen(false)}
          type="button"
        />
      )}

      <div className="grid gap-4 lg:grid-cols-[320px,1fr,340px]">
        <aside
          className={`${
            conversationsOpen ? "fixed inset-y-0 left-0 z-30 w-[85%] max-w-sm" : "hidden"
          } h-full overflow-hidden rounded-r-lg bg-panel p-4 lg:static lg:z-auto lg:block lg:h-[calc(100vh-160px)] lg:w-auto lg:max-w-none lg:rounded-lg`}
          data-testid="conversations-panel"
        >
          {renderConversationsList()}
        </aside>

        <section className="rounded-lg bg-panel p-4">
          <div className="mb-3 grid gap-2 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-slate-300">Provider Override</label>
              <select
                className="w-full rounded border border-slate-700 bg-slate-900 p-2"
                disabled={Boolean(activePinnedProviderId)}
                value={activePinnedProviderId ?? providerOverride}
                onChange={(e) => {
                  const nextOverride = e.target.value;
                  setProviderOverride(nextOverride);
                  window.localStorage.setItem(CHAT_PROVIDER_OVERRIDE_KEY, nextOverride);
                  if (!nextOverride) {
                    if (defaultProvider) {
                      setModelIndicator(`${defaultProvider.name} / ${defaultProvider.model_name}`);
                    } else {
                      setModelIndicator("Not set");
                    }
                    return;
                  }
                  const provider = providers.find((item) => item.id === nextOverride);
                  if (provider) {
                    setModelIndicator(`${provider.name} / ${provider.model_name}`);
                  }
                }}
              >
                <option value="">Use tenant default</option>
                {providers.map((provider) => (
                  <option
                    disabled={provider.provider_type === "codex" && !provider.oauth_connected}
                    key={provider.id}
                    value={provider.id}
                  >
                    {provider.name} ({provider.provider_type} / {provider.model_name}
                    {provider.provider_type === "codex" && !provider.oauth_connected ? " / OAuth disconnected" : ""})
                  </option>
                ))}
              </select>
              {activePinnedModelLabel && (
                <p className="mt-1 text-xs text-slate-400">
                  This conversation is pinned to {activePinnedModelLabel}. Start a new conversation to switch.
                </p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-300">Model Indicator</label>
              <div className="rounded border border-slate-700 bg-slate-900 p-2 text-sm">{modelIndicator}</div>
              <p className="mt-1 text-xs text-slate-400">Next message uses: {nextModelLabel}</p>
              {activePinnedModelLabel && (
                <p className="mt-1 text-xs text-slate-400">Pinned model for this conversation: {activePinnedModelLabel}</p>
              )}
            </div>
          </div>

          <div className="mb-3 h-[460px] overflow-y-auto rounded border border-slate-800 bg-slate-950 p-3" ref={messagesContainerRef}>
            <div className="space-y-3">
              {groupedMessages.map((message) => (
                <article
                  className={`rounded p-3 text-sm ${message.role === "assistant" ? "bg-slate-900" : "bg-slate-800"}`}
                  key={message.id}
                >
                  <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">{message.role}</div>
                  <div className="whitespace-pre-wrap">{message.content}</div>
                  {message.safety_flags.length > 0 && (
                    <div className="mt-2 text-xs text-amber-300">Flags: {message.safety_flags.join(", ")}</div>
                  )}
                </article>
              ))}
              {groupedMessages.length === 0 && <p className="text-sm text-slate-400">No messages yet.</p>}
            </div>
          </div>

          <form className="space-y-2" onSubmit={onSubmit}>
            {pendingInteractionType === "confirmation_required" && (
              <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                <div className="mb-2 font-medium text-amber-200">Confirmation required</div>
                <div className="flex gap-2">
                  <button
                    className="rounded bg-emerald-500 px-3 py-1.5 text-sm font-medium text-slate-950"
                    disabled={sending}
                    onClick={() => {
                      void confirmPendingAction(true);
                    }}
                    type="button"
                  >
                    Confirm
                  </button>
                  <button
                    className="rounded border border-red-500 px-3 py-1.5 text-sm text-red-200"
                    disabled={sending}
                    onClick={() => {
                      void confirmPendingAction(false);
                    }}
                    type="button"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
            {pendingInteractionType === "selection_required" && pendingOptions.length > 0 && (
              <div className="rounded border border-sky-500/40 bg-sky-500/10 p-3 text-sm">
                <div className="mb-2 font-medium text-sky-200">Select an option</div>
                <div className="flex flex-wrap gap-2">
                  {pendingOptions.map((option) => (
                    <button
                      className="rounded border border-sky-500 px-3 py-1.5 text-xs text-sky-100"
                      disabled={sending}
                      key={option.id}
                      onClick={() => {
                        void selectPendingAction(option.id);
                      }}
                      type="button"
                    >
                      {option.id}. {option.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <textarea
              className="h-24 w-full rounded border border-slate-700 bg-slate-900 p-2"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={onPromptKeyDown}
            />
            <p className="text-xs text-slate-400">
              Press Enter to send. Use Shift+Enter for a new line.
            </p>
            <p className="text-xs text-slate-400">
              You can ask: add/update/delete meetings, summarize your last emails, read email by id, or send email
              (confirmation required).
            </p>
            <div className="flex gap-2">
              <button className="rounded bg-accent px-4 py-2 font-semibold text-slate-950" disabled={sending} type="submit">
                {sending ? "Sending..." : "Send"}
              </button>
              <button
                className="rounded border border-slate-700 px-4 py-2"
                onClick={() => setShowSources(true)}
                type="button"
              >
                View Sources
              </button>
              <button
                className="rounded border border-slate-700 px-4 py-2"
                disabled={!activeConversationId || !lastAssistantMessageId}
                onClick={async () => {
                  if (!activeConversationId || !lastAssistantMessageId) {
                    return;
                  }
                  const note = window.prompt("Report note (optional):", "The answer may be incorrect.");
                  const result = await reportAnswer(activeConversationId, lastAssistantMessageId, note ?? "");
                  setStatusMessage(`Report recorded (${result.feedback_id}).`);
                }}
                type="button"
              >
                Report Answer
              </button>
            </div>
          </form>
        </section>

        <aside className="rounded-lg bg-panel p-4">
          <h2 className="mb-2 text-lg font-semibold">Citations</h2>
          <div className="space-y-2">
            {latestCitations.map((citation) => (
              <article className="rounded border border-slate-700 p-2 text-sm" key={citation.chunk_id}>
                <div className="font-medium">{citation.document_title}</div>
                <div className="text-xs text-slate-400">
                  {citation.source_type} • chunk {citation.chunk_index}
                </div>
                {citation.document_url && (
                  <a className="text-xs text-accent underline" href={citation.document_url} rel="noreferrer" target="_blank">
                    Open source
                  </a>
                )}
                <p className="mt-1 text-xs text-slate-300">{citation.snippet}</p>
              </article>
            ))}
            {latestCitations.length === 0 && <p className="text-sm text-slate-400">No citations for current response.</p>}
          </div>
        </aside>
      </div>

      {showSources && (
        <div className="fixed inset-0 z-30 bg-black/60 p-6">
          <div className="mx-auto max-w-4xl rounded-lg bg-panel p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-lg font-semibold">View Sources</h3>
              <button className="rounded border border-slate-700 px-3 py-1" onClick={() => setShowSources(false)} type="button">
                Close
              </button>
            </div>
            <div className="max-h-[65vh] space-y-2 overflow-y-auto">
              {latestCitations.map((citation) => (
                <article className="rounded border border-slate-700 p-3" key={`drawer-${citation.chunk_id}`}>
                  <div className="mb-1 font-medium">{citation.document_title}</div>
                  <div className="mb-1 text-xs text-slate-400">
                    {citation.source_type} • chunk {citation.chunk_index}
                  </div>
                  <div className="whitespace-pre-wrap text-sm">{citation.snippet}</div>
                </article>
              ))}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
