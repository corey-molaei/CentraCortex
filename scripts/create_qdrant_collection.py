#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


def main() -> None:
    parser = argparse.ArgumentParser(description="Create per-tenant Qdrant collection")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--vector-size", type=int, default=int(os.getenv("EMBEDDING_DIMENSION", "384")))
    args = parser.parse_args()

    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    client = QdrantClient(url=qdrant_url)
    collection_name = f"tenant_{args.tenant_id}"

    exists = client.collection_exists(collection_name)
    if exists:
        print(f"Collection already exists: {collection_name}")
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=args.vector_size, distance=Distance.COSINE),
    )
    print(f"Created collection: {collection_name}")


if __name__ == "__main__":
    main()
