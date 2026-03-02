export interface DocumentListItem {
  id: string;
  source_type: string;
  source_id: string;
  title: string;
  url: string | null;
  author: string | null;
  tags_json: string[];
  acl_policy_id: string | null;
  current_chunk_version: number;
  indexed_at: string | null;
  index_status: string;
  index_error: string | null;
  index_attempts: number;
  index_requested_at: string | null;
  created_at: string;
  updated_at: string;
  chunk_count: number;
}

export interface DocumentChunkRead {
  id: string;
  chunk_index: number;
  chunk_version: number;
  content: string;
  token_count: number;
  acl_policy_id: string | null;
  metadata_json: Record<string, unknown>;
}

export interface DocumentDetail {
  id: string;
  tenant_id: string;
  source_type: string;
  source_id: string;
  url: string | null;
  title: string;
  author: string | null;
  source_created_at: string | null;
  source_updated_at: string | null;
  tags_json: string[];
  metadata_json: Record<string, unknown>;
  acl_policy_id: string | null;
  current_chunk_version: number;
  indexed_at: string | null;
  index_status: string;
  index_error: string | null;
  index_attempts: number;
  index_requested_at: string | null;
  created_at: string;
  updated_at: string;
  chunks: DocumentChunkRead[];
}

export interface ReindexResponse {
  indexed_documents: number;
  indexed_chunks: number;
}

export interface ChunkSearchResultItem {
  document_id: string;
  document_title: string;
  document_url: string | null;
  source_type: string;
  chunk_id: string;
  chunk_index: number;
  snippet: string;
  score: number;
  ranker: string;
}
