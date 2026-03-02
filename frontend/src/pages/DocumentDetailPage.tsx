import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { forgetDocument, getDocument, reindexDocument } from "../api/documents";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { PageContainer } from "../layout/PageContainer";
import type { DocumentDetail } from "../types/documents";

function statusVariant(status: string): "neutral" | "success" | "warning" | "danger" {
  const value = status.toLowerCase();
  if (value === "indexed") {
    return "success";
  }
  if (value === "retry") {
    return "warning";
  }
  if (value === "failed") {
    return "danger";
  }
  return "neutral";
}

export function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!documentId) {
      return;
    }
    setError(null);
    const detail = await getDocument(documentId);
    setDocument(detail);
  }, [documentId]);

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "Failed loading document"));
  }, [load]);

  if (!documentId) {
    return <main className="p-6">Missing document id.</main>;
  }

  return (
    <PageContainer>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Document Detail</h1>
        <Link className="text-sm text-indigo-300 underline" to="/documents">
          Back to documents
        </Link>
      </div>

      {error && (
        <Alert title="Document Error" variant="danger">
          {error}
        </Alert>
      )}
      {message && (
        <Alert title="Success" variant="success">
          {message}
        </Alert>
      )}

      {document && (
        <>
          <div className="grid gap-4 xl:grid-cols-4">
            <Card className="xl:col-span-3">
              <CardHeader>
                <CardTitle>{document.title}</CardTitle>
                <CardDescription>
                  {document.source_type} / {document.source_id}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-2 text-sm text-slate-200 md:grid-cols-2">
                  <p>ACL policy: {document.acl_policy_id ?? "default"}</p>
                  <p>Chunk version: {document.current_chunk_version}</p>
                  <p>
                    Index status: <Badge variant={statusVariant(document.index_status)}>{document.index_status}</Badge>
                  </p>
                  <p>Index attempts: {document.index_attempts}</p>
                  <p>
                    Index requested: {document.index_requested_at ? new Date(document.index_requested_at).toLocaleString() : "-"}
                  </p>
                  <p>Indexed: {document.indexed_at ? new Date(document.indexed_at).toLocaleString() : "Never"}</p>
                  <p>Updated: {new Date(document.updated_at).toLocaleString()}</p>
                  <p>Author: {document.author ?? "-"}</p>
                  <p>Tags: {document.tags_json.join(", ") || "-"}</p>
                </div>
                {document.index_error && (
                  <Alert className="mt-3" title="Last indexing error" variant="danger">
                    {document.index_error}
                  </Alert>
                )}
                {document.url && (
                  <p className="mt-3 text-sm">
                    URL:{" "}
                    <a className="text-indigo-300 underline" href={document.url} rel="noreferrer" target="_blank">
                      {document.url}
                    </a>
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Actions</CardTitle>
                <CardDescription>Manual controls for recovery or cleanup.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <Button
                    className="w-full"
                    onClick={async () => {
                      const result = await reindexDocument(document.id);
                      setMessage(`Reindexed: ${result.indexed_chunks} chunks`);
                      await load();
                    }}
                    variant="primary"
                  >
                    Reindex
                  </Button>
                  <Button
                    className="w-full"
                    onClick={async () => {
                      if (!window.confirm("Forget this document permanently?")) {
                        return;
                      }
                      await forgetDocument(document.id);
                      navigate("/documents");
                    }}
                    variant="danger"
                  >
                    Forget
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle>Chunks ({document.chunks.length})</CardTitle>
              <CardDescription>Indexed text fragments used by retrieval and citation.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {document.chunks.map((chunk) => (
                  <article className="rounded-xl border border-white/10 bg-white/5 p-3" key={chunk.id}>
                    <div className="mb-1 text-xs text-slate-300">
                      Chunk #{chunk.chunk_index} | Version {chunk.chunk_version} | Tokens {chunk.token_count}
                    </div>
                    <div className="whitespace-pre-wrap text-sm text-slate-100">{chunk.content}</div>
                  </article>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </PageContainer>
  );
}
