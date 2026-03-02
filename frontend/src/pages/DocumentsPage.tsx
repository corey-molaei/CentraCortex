import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { forgetDocument, listDocuments, reindexDocument, reindexDocuments, searchDocumentChunks } from "../api/documents";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { Table, TableContainer, Td, Th } from "../components/ui/Table";
import { PageContainer } from "../layout/PageContainer";
import type { ChunkSearchResultItem, DocumentListItem } from "../types/documents";

function renderIndexStatus(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "indexed") {
    return <Badge variant="success">Indexed</Badge>;
  }
  if (normalized === "retry") {
    return <Badge variant="warning">Retrying</Badge>;
  }
  if (normalized === "failed") {
    return <Badge variant="danger">Failed</Badge>;
  }
  return <Badge variant="neutral">Pending</Badge>;
}

export function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [sourceType, setSourceType] = useState("");
  const [tag, setTag] = useState("");
  const [aclPolicyId, setAclPolicyId] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [query, setQuery] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<ChunkSearchResultItem[]>([]);
  const [busyDocId, setBusyDocId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    setError(null);
    const items = await listDocuments({
      source_type: sourceType || undefined,
      tag: tag || undefined,
      acl_policy_id: aclPolicyId || undefined,
      created_from: createdFrom || undefined,
      created_to: createdTo || undefined,
      q: query || undefined
    });
    setDocuments(items);
  }, [aclPolicyId, createdFrom, createdTo, query, sourceType, tag]);

  useEffect(() => {
    loadDocuments().catch((err) => setError(err instanceof Error ? err.message : "Failed loading documents"));
  }, [loadDocuments]);

  async function onFilterSubmit(event: FormEvent) {
    event.preventDefault();
    await loadDocuments();
  }

  async function onSearchSubmit(event: FormEvent) {
    event.preventDefault();
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    try {
      const response = await searchDocumentChunks(searchQuery.trim(), 10);
      setSearchResults(response.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    }
  }

  return (
    <PageContainer>
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

      <div className="mt-4 grid gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>Document Filters</CardTitle>
            <CardDescription>Filter by connector source, policy, metadata, and date ranges.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="grid gap-2 md:grid-cols-3" onSubmit={onFilterSubmit}>
              <input
                className="rounded-lg border border-white/15 bg-white/5 p-2 text-sm"
                onChange={(e) => setSourceType(e.target.value)}
                placeholder="Source type"
                value={sourceType}
              />
              <input
                className="rounded-lg border border-white/15 bg-white/5 p-2 text-sm"
                onChange={(e) => setTag(e.target.value)}
                placeholder="Tag"
                value={tag}
              />
              <input
                className="rounded-lg border border-white/15 bg-white/5 p-2 text-sm"
                onChange={(e) => setAclPolicyId(e.target.value)}
                placeholder="ACL policy ID"
                value={aclPolicyId}
              />
              <input
                className="rounded-lg border border-white/15 bg-white/5 p-2 text-sm"
                onChange={(e) => setCreatedFrom(e.target.value)}
                type="date"
                value={createdFrom}
              />
              <input
                className="rounded-lg border border-white/15 bg-white/5 p-2 text-sm"
                onChange={(e) => setCreatedTo(e.target.value)}
                type="date"
                value={createdTo}
              />
              <input
                className="rounded-lg border border-white/15 bg-white/5 p-2 text-sm"
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search title/body"
                value={query}
              />
              <div className="flex flex-wrap gap-2 md:col-span-3">
                <Button type="submit" variant="primary">
                  Apply Filters
                </Button>
                <Button
                  onClick={async () => {
                    setSourceType("");
                    setTag("");
                    setAclPolicyId("");
                    setCreatedFrom("");
                    setCreatedTo("");
                    setQuery("");
                    const items = await listDocuments({});
                    setDocuments(items);
                  }}
                  variant="secondary"
                >
                  Clear
                </Button>
                <Button
                  onClick={async () => {
                    const response = await reindexDocuments({ document_ids: documents.map((doc) => doc.id) });
                    setMessage(`Reindexed ${response.indexed_documents} documents (${response.indexed_chunks} chunks).`);
                    await loadDocuments();
                  }}
                  variant="secondary"
                >
                  Reindex Filtered
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Hybrid Search</CardTitle>
            <CardDescription>BM25 + vector retrieval with ACL checks on every chunk.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex gap-2" onSubmit={onSearchSubmit}>
              <input
                className="w-full rounded-lg border border-white/15 bg-white/5 p-2 text-sm"
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search chunks (ACL enforced)"
                value={searchQuery}
              />
              <Button type="submit" variant="secondary">
                Search
              </Button>
            </form>
            {searchResults.length > 0 && (
              <div className="mt-3 space-y-2">
                {searchResults.map((item) => (
                  <article className="rounded-xl border border-white/10 bg-white/5 p-3" key={item.chunk_id}>
                    <div className="mb-1 text-xs text-slate-300">
                      {item.document_title} ({item.source_type}) | score {item.score.toFixed(3)} via {item.ranker}
                    </div>
                    <div className="text-sm text-slate-100">{item.snippet}</div>
                  </article>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Documents ({documents.length})</CardTitle>
          <CardDescription>Track indexing status and run manual operations when needed.</CardDescription>
        </CardHeader>
        <CardContent>
          <TableContainer>
            <Table>
              <thead>
                <tr>
                  <Th>Title</Th>
                  <Th>Source</Th>
                  <Th>Tags</Th>
                  <Th>ACL</Th>
                  <Th>Chunk Version</Th>
                  <Th>Chunks</Th>
                  <Th>Index Status</Th>
                  <Th>Updated</Th>
                  <Th>Actions</Th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id}>
                    <Td>
                      <div className="font-medium">{doc.title}</div>
                      <div className="text-xs text-slate-400">{doc.id}</div>
                    </Td>
                    <Td>{doc.source_type}</Td>
                    <Td>{doc.tags_json.join(", ") || "-"}</Td>
                    <Td>{doc.acl_policy_id ?? "default"}</Td>
                    <Td>{doc.current_chunk_version}</Td>
                    <Td>{doc.chunk_count}</Td>
                    <Td>
                      <div className="flex flex-col gap-1">
                        <div>{renderIndexStatus(doc.index_status)}</div>
                        {doc.index_error && (
                          <p className="max-w-[240px] truncate text-xs text-red-300" title={doc.index_error}>
                            {doc.index_error}
                          </p>
                        )}
                      </div>
                    </Td>
                    <Td>{new Date(doc.updated_at).toLocaleString()}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-2">
                        <Link className="rounded-lg border border-white/15 bg-white/5 px-3 py-1 text-xs" to={`/documents/${doc.id}`}>
                          View
                        </Link>
                        <Button
                          disabled={busyDocId === doc.id}
                          onClick={async () => {
                            setBusyDocId(doc.id);
                            try {
                              const response = await reindexDocument(doc.id);
                              setMessage(`Reindexed ${doc.title} (${response.indexed_chunks} chunks).`);
                              await loadDocuments();
                            } finally {
                              setBusyDocId(null);
                            }
                          }}
                          size="sm"
                          variant="secondary"
                        >
                          Reindex
                        </Button>
                        <Button
                          disabled={busyDocId === doc.id}
                          onClick={async () => {
                            if (!window.confirm(`Forget document "${doc.title}" permanently?`)) {
                              return;
                            }
                            setBusyDocId(doc.id);
                            try {
                              await forgetDocument(doc.id);
                              setMessage(`Deleted document ${doc.title}.`);
                              await loadDocuments();
                            } finally {
                              setBusyDocId(null);
                            }
                          }}
                          size="sm"
                          variant="danger"
                        >
                          Forget
                        </Button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    </PageContainer>
  );
}
