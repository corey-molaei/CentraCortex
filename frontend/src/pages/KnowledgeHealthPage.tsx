import { useEffect, useState } from "react";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { getKnowledgeHealth } from "../api/workspace";
import { PageContainer } from "../layout/PageContainer";
import type { KnowledgeHealthResponse } from "../types/workspace";

export function KnowledgeHealthPage() {
  const [data, setData] = useState<KnowledgeHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getKnowledgeHealth()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load knowledge health"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <PageContainer>
      <Card>
        <CardHeader>
          <CardTitle>Knowledge Health</CardTitle>
        </CardHeader>
        <CardContent>
          {loading && <p className="text-sm text-slate-300">Loading knowledge health...</p>}
          {error && (
            <Alert title="Knowledge Health Error" variant="danger">
              {error}
            </Alert>
          )}
          {data && (
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded border border-white/10 bg-white/5 p-3">
                  <p className="text-xs uppercase text-slate-400">Documents</p>
                  <p className="text-xl font-semibold text-white">{data.total_documents}</p>
                </div>
                <div className="rounded border border-white/10 bg-white/5 p-3">
                  <p className="text-xs uppercase text-slate-400">Chunks</p>
                  <p className="text-xl font-semibold text-white">{data.total_chunks}</p>
                </div>
                <div className="rounded border border-white/10 bg-white/5 p-3">
                  <p className="text-xs uppercase text-slate-400">Last Sync</p>
                  <p className="text-sm text-slate-100">{data.latest_sync_at ?? "-"}</p>
                </div>
              </div>

              <div className="overflow-x-auto rounded border border-white/10">
                <table className="min-w-full text-sm">
                  <thead className="bg-white/5 text-left text-slate-300">
                    <tr>
                      <th className="px-3 py-2">Source</th>
                      <th className="px-3 py-2">Docs</th>
                      <th className="px-3 py-2">Indexed</th>
                      <th className="px-3 py-2">Pending</th>
                      <th className="px-3 py-2">Retry</th>
                      <th className="px-3 py-2">Failed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sources.map((source) => (
                      <tr className="border-t border-white/10" key={source.source_type}>
                        <td className="px-3 py-2">
                          <Badge variant="info">{source.source_type}</Badge>
                        </td>
                        <td className="px-3 py-2">{source.documents}</td>
                        <td className="px-3 py-2">{source.indexed}</td>
                        <td className="px-3 py-2">{source.pending}</td>
                        <td className="px-3 py-2">{source.retry}</td>
                        <td className="px-3 py-2">{source.failed}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div>
                <h3 className="mb-2 text-sm font-semibold text-white">Recent Errors</h3>
                {data.recent_errors.length === 0 ? (
                  <p className="text-sm text-slate-300">No recent connector sync errors.</p>
                ) : (
                  <ul className="space-y-1 text-sm text-slate-200">
                    {data.recent_errors.map((item, index) => (
                      <li key={`${item}-${index}`}>- {item}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </PageContainer>
  );
}
