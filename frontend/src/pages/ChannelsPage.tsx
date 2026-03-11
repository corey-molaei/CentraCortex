import { useEffect, useMemo, useState } from "react";
import {
  listChannelConnectors,
  testFacebookConnector,
  testTelegramConnector,
  testWhatsAppConnector,
  updateFacebookConnector,
  updateTelegramConnector,
  updateWhatsAppConnector
} from "../api/workspace";
import { Alert } from "../components/ui/Alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { PageContainer } from "../layout/PageContainer";
import type { ChannelConnector } from "../types/workspace";

type Drafts = {
  telegramBotToken: string;
  telegramWebhookSecret: string;
  whatsappAccessToken: string;
  whatsappPhoneNumberId: string;
  whatsappBusinessAccountId: string;
  whatsappVerifyToken: string;
  facebookPageAccessToken: string;
  facebookPageId: string;
  facebookAppId: string;
  facebookAppSecret: string;
  facebookVerifyToken: string;
};

const EMPTY_DRAFTS: Drafts = {
  telegramBotToken: "",
  telegramWebhookSecret: "",
  whatsappAccessToken: "",
  whatsappPhoneNumberId: "",
  whatsappBusinessAccountId: "",
  whatsappVerifyToken: "",
  facebookPageAccessToken: "",
  facebookPageId: "",
  facebookAppId: "",
  facebookAppSecret: "",
  facebookVerifyToken: ""
};

export function ChannelsPage() {
  const [connectors, setConnectors] = useState<ChannelConnector[]>([]);
  const [drafts, setDrafts] = useState<Drafts>(EMPTY_DRAFTS);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const byChannel = useMemo(() => {
    return {
      telegram: connectors.find((row) => row.channel === "telegram") ?? null,
      whatsapp: connectors.find((row) => row.channel === "whatsapp") ?? null,
      facebook: connectors.find((row) => row.channel === "facebook") ?? null
    };
  }, [connectors]);

  async function load() {
    setConnectors(await listChannelConnectors());
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "Failed to load channels"));
  }, []);

  return (
    <PageContainer>
      <Card>
        <CardHeader>
          <CardTitle>Chat Channels</CardTitle>
          <CardDescription>Configure Telegram, WhatsApp, and Facebook Messenger connectors.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <Alert title="Channels Error" variant="danger">
              {error}
            </Alert>
          )}
          {message && (
            <Alert title="Status" variant="success">
              {message}
            </Alert>
          )}

          <section className="rounded border border-white/10 bg-white/5 p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="font-semibold text-white">Telegram</h3>
              <span className="text-xs text-slate-300">
                {byChannel.telegram?.configured ? "Configured" : "Not configured"} | {byChannel.telegram?.enabled ? "Enabled" : "Disabled"}
              </span>
            </div>
            {byChannel.telegram?.id && (
              <div className="mb-2 rounded border border-slate-700 bg-slate-900/70 p-2 text-xs text-slate-300">
                <div>Webhook URL</div>
                <div className="break-all text-slate-200">
                  {`${window.location.origin}/api/v1/channels/telegram/webhook/${byChannel.telegram.id}`}
                </div>
                <div className="mt-1 text-slate-400">Click Test after saving to register this webhook with Telegram.</div>
              </div>
            )}
            <div className="grid gap-2 md:grid-cols-2">
              <input
                className="rounded border border-slate-700 bg-slate-900 p-2"
                onChange={(event) => setDrafts((prev) => ({ ...prev, telegramBotToken: event.target.value }))}
                placeholder="Bot token"
                value={drafts.telegramBotToken}
              />
              <input
                className="rounded border border-slate-700 bg-slate-900 p-2"
                onChange={(event) => setDrafts((prev) => ({ ...prev, telegramWebhookSecret: event.target.value }))}
                placeholder="Webhook secret"
                value={drafts.telegramWebhookSecret}
              />
              <label className="flex items-center gap-2 text-sm">
                <input
                  checked={Boolean(byChannel.telegram?.enabled)}
                  onChange={async (event) => {
                    try {
                      const updated = await updateTelegramConnector({ enabled: event.target.checked });
                      setConnectors((prev) => prev.map((item) => (item.channel === "telegram" ? updated : item)));
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Failed to toggle Telegram");
                    }
                  }}
                  type="checkbox"
                />
                Enabled
              </label>
            </div>
            <div className="mt-2 flex gap-2">
              <button
                className="rounded border border-slate-700 px-3 py-2 text-sm"
                onClick={() => {
                  updateTelegramConnector({
                    bot_token: drafts.telegramBotToken || undefined,
                    webhook_secret: drafts.telegramWebhookSecret || undefined
                  })
                    .then((updated) => {
                      setConnectors((prev) => prev.map((item) => (item.channel === "telegram" ? updated : item)));
                      setMessage("Telegram connector updated.");
                    })
                    .catch((err) => setError(err instanceof Error ? err.message : "Failed to update Telegram"));
                }}
                type="button"
              >
                Save
              </button>
              <button
                className="rounded border border-slate-700 px-3 py-2 text-sm"
                onClick={() => {
                  testTelegramConnector()
                    .then((res) => setMessage(res.message))
                    .catch((err) => setError(err instanceof Error ? err.message : "Telegram test failed"));
                }}
                type="button"
              >
                Test
              </button>
            </div>
          </section>

          <section className="rounded border border-white/10 bg-white/5 p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="font-semibold text-white">WhatsApp</h3>
              <span className="text-xs text-slate-300">
                {byChannel.whatsapp?.configured ? "Configured" : "Not configured"} | {byChannel.whatsapp?.enabled ? "Enabled" : "Disabled"}
              </span>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              <input className="rounded border border-slate-700 bg-slate-900 p-2" onChange={(event) => setDrafts((prev) => ({ ...prev, whatsappAccessToken: event.target.value }))} placeholder="Access token" value={drafts.whatsappAccessToken} />
              <input className="rounded border border-slate-700 bg-slate-900 p-2" onChange={(event) => setDrafts((prev) => ({ ...prev, whatsappPhoneNumberId: event.target.value }))} placeholder="Phone number id" value={drafts.whatsappPhoneNumberId} />
              <input className="rounded border border-slate-700 bg-slate-900 p-2" onChange={(event) => setDrafts((prev) => ({ ...prev, whatsappBusinessAccountId: event.target.value }))} placeholder="Business account id" value={drafts.whatsappBusinessAccountId} />
              <input className="rounded border border-slate-700 bg-slate-900 p-2" onChange={(event) => setDrafts((prev) => ({ ...prev, whatsappVerifyToken: event.target.value }))} placeholder="Verify token" value={drafts.whatsappVerifyToken} />
              <label className="flex items-center gap-2 text-sm">
                <input
                  checked={Boolean(byChannel.whatsapp?.enabled)}
                  onChange={async (event) => {
                    try {
                      const updated = await updateWhatsAppConnector({ enabled: event.target.checked });
                      setConnectors((prev) => prev.map((item) => (item.channel === "whatsapp" ? updated : item)));
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Failed to toggle WhatsApp");
                    }
                  }}
                  type="checkbox"
                />
                Enabled
              </label>
            </div>
            <div className="mt-2 flex gap-2">
              <button
                className="rounded border border-slate-700 px-3 py-2 text-sm"
                onClick={() => {
                  updateWhatsAppConnector({
                    access_token: drafts.whatsappAccessToken || undefined,
                    phone_number_id: drafts.whatsappPhoneNumberId || undefined,
                    business_account_id: drafts.whatsappBusinessAccountId || undefined,
                    verify_token: drafts.whatsappVerifyToken || undefined
                  })
                    .then((updated) => {
                      setConnectors((prev) => prev.map((item) => (item.channel === "whatsapp" ? updated : item)));
                      setMessage("WhatsApp connector updated.");
                    })
                    .catch((err) => setError(err instanceof Error ? err.message : "Failed to update WhatsApp"));
                }}
                type="button"
              >
                Save
              </button>
              <button
                className="rounded border border-slate-700 px-3 py-2 text-sm"
                onClick={() => {
                  testWhatsAppConnector()
                    .then((res) => setMessage(res.message))
                    .catch((err) => setError(err instanceof Error ? err.message : "WhatsApp test failed"));
                }}
                type="button"
              >
                Test
              </button>
            </div>
          </section>

          <section className="rounded border border-white/10 bg-white/5 p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="font-semibold text-white">Facebook Messenger</h3>
              <span className="text-xs text-slate-300">
                {byChannel.facebook?.configured ? "Configured" : "Not configured"} | {byChannel.facebook?.enabled ? "Enabled" : "Disabled"}
              </span>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              <input className="rounded border border-slate-700 bg-slate-900 p-2" onChange={(event) => setDrafts((prev) => ({ ...prev, facebookPageAccessToken: event.target.value }))} placeholder="Page access token" value={drafts.facebookPageAccessToken} />
              <input className="rounded border border-slate-700 bg-slate-900 p-2" onChange={(event) => setDrafts((prev) => ({ ...prev, facebookPageId: event.target.value }))} placeholder="Page id" value={drafts.facebookPageId} />
              <input className="rounded border border-slate-700 bg-slate-900 p-2" onChange={(event) => setDrafts((prev) => ({ ...prev, facebookAppId: event.target.value }))} placeholder="App id" value={drafts.facebookAppId} />
              <input className="rounded border border-slate-700 bg-slate-900 p-2" onChange={(event) => setDrafts((prev) => ({ ...prev, facebookAppSecret: event.target.value }))} placeholder="App secret" value={drafts.facebookAppSecret} />
              <input className="rounded border border-slate-700 bg-slate-900 p-2" onChange={(event) => setDrafts((prev) => ({ ...prev, facebookVerifyToken: event.target.value }))} placeholder="Verify token" value={drafts.facebookVerifyToken} />
              <label className="flex items-center gap-2 text-sm">
                <input
                  checked={Boolean(byChannel.facebook?.enabled)}
                  onChange={async (event) => {
                    try {
                      const updated = await updateFacebookConnector({ enabled: event.target.checked });
                      setConnectors((prev) => prev.map((item) => (item.channel === "facebook" ? updated : item)));
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Failed to toggle Facebook");
                    }
                  }}
                  type="checkbox"
                />
                Enabled
              </label>
            </div>
            <div className="mt-2 flex gap-2">
              <button
                className="rounded border border-slate-700 px-3 py-2 text-sm"
                onClick={() => {
                  updateFacebookConnector({
                    page_access_token: drafts.facebookPageAccessToken || undefined,
                    page_id: drafts.facebookPageId || undefined,
                    app_id: drafts.facebookAppId || undefined,
                    app_secret: drafts.facebookAppSecret || undefined,
                    verify_token: drafts.facebookVerifyToken || undefined
                  })
                    .then((updated) => {
                      setConnectors((prev) => prev.map((item) => (item.channel === "facebook" ? updated : item)));
                      setMessage("Facebook connector updated.");
                    })
                    .catch((err) => setError(err instanceof Error ? err.message : "Failed to update Facebook"));
                }}
                type="button"
              >
                Save
              </button>
              <button
                className="rounded border border-slate-700 px-3 py-2 text-sm"
                onClick={() => {
                  testFacebookConnector()
                    .then((res) => setMessage(res.message))
                    .catch((err) => setError(err instanceof Error ? err.message : "Facebook test failed"));
                }}
                type="button"
              >
                Test
              </button>
            </div>
          </section>
        </CardContent>
      </Card>
    </PageContainer>
  );
}
