"""Document ingestion pipeline for Agentic RAG.

This module provides IngestionPipeline class for loading, parsing, chunking,
embedding, and upserting documents to Qdrant with multi-vector embeddings.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

# Suppress HuggingFace Hub progress bars globally
# Set ALL possible environment variables BEFORE any imports
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_TQDM"] = "1"
os.environ["TQDM_DISABLE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["DISABLE_TQDM"] = "1"

# Use huggingface_hub's built-in API to disable progress bars
try:
    from huggingface_hub.utils import disable_progress_bars
    disable_progress_bars()
except ImportError:
    try:
        from huggingface_hub import disable_progress_bars
        disable_progress_bars()
    except ImportError:
        pass

from fastembed import TextEmbedding, SparseTextEmbedding, LateInteractionTextEmbedding
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from llmaven.agentic.settings import config
from llmaven.agentic.vector_store.qdrant_manager import QdrantManager
from llmaven.agentic.exceptions import IngestionError, EmbeddingError
from qdrant_client.models import PointStruct


class IngestionPipeline:
    """Pipeline for ingesting documents into Qdrant with multi-vector embeddings.

    The pipeline performs the following steps:
    1. Load: Traverse directories and load supported file types
    2. Parse: Extract text and metadata using docling (with fallback)
    3. Chunk: Split documents into chunks using hybrid chunking
    4. Embed: Generate dense, sparse, and ColBERT embeddings
    5. Upsert: Store chunks as points in Qdrant

    Attributes:
        qdrant_manager: QdrantManager instance
        collection_name: Name of the Qdrant collection
        batch_size: Number of documents to process per batch
    """

    # Supported file extensions
    SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".html", ".htm"}

    def __init__(
        self,
        collection_name: str | None = None,
        qdrant_manager: QdrantManager | None = None,
        batch_size: int = 100,
    ):
        """Initialize IngestionPipeline.

        Args:
            collection_name: Name of the Qdrant collection (defaults to config)
            qdrant_manager: QdrantManager instance (creates new if None)
            batch_size: Number of documents to process per batch
        """
        self.collection_name = collection_name or config.collection_name
        self.qdrant_manager = qdrant_manager or QdrantManager()
        self.batch_size = batch_size

        # Initialize embedding models (lazy loading)
        self._dense_model: TextEmbedding | None = None
        self._sparse_model: SparseTextEmbedding | None = None
        self._colbert_model: LateInteractionTextEmbedding | None = None
        self._models_initialized = False

    def _ensure_models_loaded(self) -> None:
        """Ensure embedding models are loaded, with clear progress messaging."""
        if self._models_initialized:
            return

        # Print a clear header message explaining what's happening
        # This appears BEFORE any HuggingFace Hub progress bars
        from rich.console import Console
        console = Console()
        console.print("\n[yellow]📦 Loading embedding models (HuggingFace model files will be fetched if not cached)...[/yellow]")

        try:
            # Load models - HuggingFace Hub may show "Fetching X files" progress bars
            # This is expected behavior for model file downloads/cache checks
            if self._dense_model is None:
                console.print(f"  [dim]• Dense model: {config.dense_model}[/dim]")
                self._dense_model = TextEmbedding(model_name=config.dense_model)
            
            if self._sparse_model is None:
                console.print(f"  [dim]• Sparse model: {config.sparse_model}[/dim]")
                self._sparse_model = SparseTextEmbedding(model_name=config.sparse_model)
            
            if self._colbert_model is None:
                console.print(f"  [dim]• ColBERT model: {config.colbert_model}[/dim]")
                self._colbert_model = LateInteractionTextEmbedding(model_name=config.colbert_model)
            
            console.print("[green]✅ Embedding models ready[/green]\n")
            self._models_initialized = True
        except Exception as e:
            raise EmbeddingError(f"Failed to initialize embedding models: {e}") from e

    def load(self, directories: list[str]) -> list[dict[str, Any]]:
        """Load documents from directories.

        Traverses directories recursively and loads supported file types.

        Args:
            directories: List of directory paths to load from

        Returns:
            List of document dicts with 'file_path' and 'content' keys

        Raises:
            IngestionError: If directory doesn't exist or loading fails
        """
        documents = []

        for directory in directories:
            dir_path = Path(directory)
            if not dir_path.exists():
                raise IngestionError(f"Directory does not exist: {directory}")

            if not dir_path.is_dir():
                raise IngestionError(f"Path is not a directory: {directory}")

            # Recursively find supported files
            for file_path in dir_path.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                    try:
                        # Read file content
                        if file_path.suffix.lower() == ".pdf":
                            # PDF files: read as bytes for docling
                            content = file_path.read_bytes()
                        else:
                            # Text files: read as string
                            content = file_path.read_text(encoding="utf-8", errors="ignore")

                        documents.append({
                            "file_path": str(file_path),
                            "content": content,
                        })
                    except Exception as e:
                        # Continue processing other files if one fails
                        continue

        return documents

    def parse(self, document: dict[str, Any]) -> dict[str, Any]:
        """Parse document and extract text and metadata.

        Uses docling for PDF and structured documents, with fallback to
        basic text extraction for other formats.

        Args:
            document: Document dict with 'file_path' and 'content'

        Returns:
            Parsed document dict with 'text', 'file_path', and optional metadata
        """
        file_path = Path(document["file_path"])
        content = document["content"]
        file_ext = file_path.suffix.lower()

        parsed = {
            "file_path": str(file_path),
        }

        # Try docling for PDF and structured documents
        if file_ext == ".pdf":
            try:
                from docling.document_converter import DocumentConverter

                converter = DocumentConverter()
                doc = converter.convert(content)
                doc_dict = doc.document.export_to_dict()

                # Extract text content
                text_parts = []
                heading_hierarchy = []

                for item in doc_dict.get("content", []):
                    if "text" in item:
                        text_parts.append(item["text"])
                    if "heading" in item:
                        heading_hierarchy.append(item["heading"].get("text", ""))

                parsed["text"] = "\n\n".join(text_parts)
                if heading_hierarchy:
                    parsed["heading_hierarchy"] = " > ".join(heading_hierarchy)

            except Exception:
                # Fallback to PyMuPDF
                try:
                    import fitz  # PyMuPDF

                    doc = fitz.open(stream=content, filetype="pdf")
                    text_parts = []
                    for page in doc:
                        text_parts.append(page.get_text())
                    parsed["text"] = "\n\n".join(text_parts)
                    doc.close()
                except Exception as e:
                    raise IngestionError(f"Failed to parse PDF: {e}") from e

        else:
            # Text-based files: use content directly
            parsed["text"] = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")

        return parsed

    def chunk(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        """Chunk document into smaller pieces.

        Uses docling's hybrid chunking strategy if available, otherwise
        uses simple text splitting.

        Args:
            document: Parsed document dict

        Returns:
            List of chunk dicts with 'text', 'file_path', and metadata
        """
        text = document.get("text", "")
        file_path = document.get("file_path", "")

        # Simple chunking strategy: split by paragraphs, then by sentences
        # This is a basic implementation; docling hybrid chunking can be added later
        paragraphs = text.split("\n\n")
        chunks = []

        for para_idx, paragraph in enumerate(paragraphs):
            if not paragraph.strip():
                continue

            # Split long paragraphs into sentences
            sentences = paragraph.split(". ")
            current_chunk = []

            for sentence in sentences:
                current_chunk.append(sentence)
                # Create chunk when we have enough content (~500 chars)
                chunk_text = ". ".join(current_chunk)
                if len(chunk_text) > 500:
                    chunks.append({
                        "text": chunk_text,
                        "file_path": file_path,
                        "chunk_index": len(chunks),
                        "heading_hierarchy": document.get("heading_hierarchy"),
                    })
                    current_chunk = []

            # Add remaining content as final chunk
            if current_chunk:
                chunk_text = ". ".join(current_chunk)
                if chunk_text.strip():
                    chunks.append({
                        "text": chunk_text,
                        "file_path": file_path,
                        "chunk_index": len(chunks),
                        "heading_hierarchy": document.get("heading_hierarchy"),
                    })

        # If no chunks created (very short document), create one chunk
        if not chunks and text.strip():
            chunks.append({
                "text": text,
                "file_path": file_path,
                "chunk_index": 0,
                "heading_hierarchy": document.get("heading_hierarchy"),
            })

        return chunks

    def embed(self, chunk: dict[str, Any]) -> dict[str, Any]:
        """Generate embeddings for a chunk.

        Generates dense, sparse, and ColBERT embeddings using fastembed.

        Args:
            chunk: Chunk dict with 'text' key

        Returns:
            Chunk dict with added 'dense', 'sparse', and 'colbert' vectors

        Raises:
            EmbeddingError: If embedding generation fails
        """
        text = chunk.get("text", "")
        if not text:
            raise EmbeddingError("Cannot embed empty chunk")

        try:
            # Ensure models are loaded (will be initialized on first call)
            if not self._models_initialized:
                self._ensure_models_loaded()

            # Generate embeddings
            dense_vec = list(self._dense_model.embed([text]))[0]
            sparse_embedding = list(self._sparse_model.embed([text]))[0]
            colbert_vec = list(self._colbert_model.embed([text]))[0]

            # Convert numpy arrays to lists if needed
            if hasattr(dense_vec, "tolist"):
                dense_vec = dense_vec.tolist()
            if hasattr(colbert_vec, "tolist"):
                colbert_vec = colbert_vec.tolist()

            # Convert sparse embedding to dict format for Qdrant
            if hasattr(sparse_embedding, "indices"):
                sparse_vec = {
                    "indices": sparse_embedding.indices.tolist(),
                    "values": sparse_embedding.values.tolist(),
                }
            else:
                sparse_vec = sparse_embedding

            chunk["dense"] = dense_vec
            chunk["sparse"] = sparse_vec
            chunk["colbert"] = colbert_vec

            return chunk

        except Exception as e:
            raise EmbeddingError(f"Failed to generate embeddings: {e}") from e

    def upsert(self, embedded_chunks: list[dict[str, Any]], force: bool = False) -> None:
        """Upsert embedded chunks to Qdrant.

        Converts embedded chunks to PointStruct objects and upserts them.

        Args:
            embedded_chunks: List of embedded chunk dicts
            force: If True, recreate collection before upserting
        """
        # Ensure collection exists
        self.qdrant_manager.ensure_collection(self.collection_name, force=force)

        # Convert chunks to PointStruct objects
        points = []
        for chunk in embedded_chunks:
            # Generate point ID from content hash
            content_hash = hashlib.md5(chunk["text"].encode()).hexdigest()
            point_id = int(content_hash[:16], 16)  # Use first 16 hex chars as int

            point = PointStruct(
                id=point_id,
                vector={
                    "dense": chunk["dense"],
                    "sparse": chunk["sparse"],
                    "colbert": chunk["colbert"],
                },
                payload={
                    "text": chunk["text"],
                    "file_path": chunk["file_path"],
                    "chunk_index": chunk.get("chunk_index", 0),
                    "content_hash": content_hash,
                    "heading_hierarchy": chunk.get("heading_hierarchy"),
                },
            )
            points.append(point)

        # Upsert points
        self.qdrant_manager.upsert_points(self.collection_name, points)

    def ingest(
        self,
        directories: list[str],
        force: bool = False,
    ) -> None:
        """Run complete ingestion pipeline.

        Loads, parses, chunks, embeds, and upserts documents from directories.

        Args:
            directories: List of directory paths to ingest
            force: If True, recreate collection before ingesting
        """
        # Initialize models BEFORE starting Rich Progress
        # This ensures model loading messages appear cleanly before progress bars
        if not self._models_initialized:
            self._ensure_models_loaded()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        ) as progress:
            # Load documents
            task_load = progress.add_task("[cyan]Loading documents from directories...", total=None)
            documents = self.load(directories)
            progress.update(task_load, description=f"[cyan]Found {len(documents)} document(s) to process")
            progress.remove_task(task_load)

            # Process documents in batches
            total_chunks = 0
            for batch_start in range(0, len(documents), self.batch_size):
                batch = documents[batch_start:batch_start + self.batch_size]
                task_batch = progress.add_task(
                    f"Processing batch {batch_start // self.batch_size + 1}...",
                    total=len(batch),
                )

                all_chunks = []
                for doc in batch:
                    try:
                        # Parse
                        parsed = self.parse(doc)
                        # Chunk
                        chunks = self.chunk(parsed)
                        all_chunks.extend(chunks)
                        progress.advance(task_batch)
                    except Exception as e:
                        # Continue processing other documents
                        continue

                # Embed chunks (models should already be initialized)
                task_embed = progress.add_task("[magenta]Embedding chunks...", total=len(all_chunks))
                embedded_chunks = []
                for chunk in all_chunks:
                    try:
                        embedded = self.embed(chunk)
                        embedded_chunks.append(embedded)
                        progress.advance(task_embed)
                    except Exception as e:
                        # Continue processing other chunks
                        continue

                # Upsert batch
                if embedded_chunks:
                    task_upsert = progress.add_task("Upserting to Qdrant...", total=1)
                    self.upsert(embedded_chunks, force=force and batch_start == 0)
                    progress.update(task_upsert, completed=1)
                    total_chunks += len(embedded_chunks)

            progress.add_task(f"✅ Ingested {total_chunks} chunks from {len(documents)} documents", completed=1)

