import { FormEvent, useCallback, useEffect, useState } from "react";
import { connectorStatus, getConnectorConfig, putConnectorConfig, testConnector, uploadFiles } from "../../api/connectors";
import { ConnectorRuns } from "../../components/connectors/ConnectorRuns";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/Card";
import { PageContainer } from "../../layout/PageContainer";
import type { ConnectorStatus, SyncRun } from "../../types/connectors";

export function FileUploadConnectorPage() {
  const [allowedExtensions, setAllowedExtensions] = useState("txt,pdf,docx,xls,xlsx,doc");
  const [enabled, setEnabled] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async () => {
    const config = await getConnectorConfig<{ allowed_extensions: string[]; status: ConnectorStatus }>("file-upload");
    if (config) {
      setAllowedExtensions(config.allowed_extensions.join(","));
      setStatus(config.status);
    }
    setRuns(await connectorStatus("file-upload"));
  }, []);

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "Failed loading file connector"));
  }, [load]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    try {
      await putConnectorConfig("file-upload", {
        allowed_extensions: allowedExtensions
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        enabled
      });
      setMessage("File connector configuration saved.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save file connector config");
    }
  }

  async function onUpload(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    if (!files.length) {
      setError("Choose at least one file before uploading.");
      return;
    }

    setUploading(true);
    try {
      await putConnectorConfig("file-upload", {
        allowed_extensions: allowedExtensions
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        enabled
      });
      const result = await uploadFiles(files);
      setMessage(`Uploaded ${result.items_synced} file(s). Indexing is queued asynchronously.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <PageContainer>
      {error && (
        <Alert title="Connector Error" variant="danger">
          {error}
        </Alert>
      )}
      {message && (
        <Alert title="Success" variant="success">
          {message}
        </Alert>
      )}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>File Upload Connector Wizard</CardTitle>
            <CardDescription>Configure extension policy and upload files for ingestion.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-3" onSubmit={onSave}>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Step 1: Policy</h2>
              <input
                className="w-full rounded-lg border border-white/15 bg-white/5 p-2 text-sm"
                onChange={(e) => setAllowedExtensions(e.target.value)}
                placeholder="txt,pdf,docx,xls,xlsx,doc"
                value={allowedExtensions}
              />
              <label className="flex items-center gap-2 text-sm text-slate-200">
                <input checked={enabled} onChange={(e) => setEnabled(e.target.checked)} type="checkbox" />
                Enabled
              </label>
              <div className="flex flex-wrap gap-2">
                <Button type="submit" variant="primary">
                  Save
                </Button>
                <Button
                  onClick={async () => {
                    const result = await testConnector("file-upload");
                    setMessage(result.message);
                  }}
                  variant="secondary"
                >
                  Test Connection
                </Button>
              </div>
            </form>

            <form className="mt-7 space-y-3 border-t border-white/10 pt-4" onSubmit={onUpload}>
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Step 2: Upload Files</h3>
              <input
                className="block w-full rounded-lg border border-white/15 bg-white/5 p-2 text-sm"
                multiple
                onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                type="file"
              />
              {files.length > 0 && <p className="text-xs text-slate-300">{files.length} file(s) selected</p>}
              <Button disabled={uploading} type="submit" variant="secondary">
                {uploading ? "Uploading..." : "Upload and Ingest"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Sync Status</CardTitle>
            <CardDescription>Review last run, item counts, and errors for this connector.</CardDescription>
          </CardHeader>
          <CardContent>
            <ConnectorRuns runs={runs} status={status} />
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
