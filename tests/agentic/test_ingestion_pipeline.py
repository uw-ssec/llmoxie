"""Tests for IngestionPipeline class.

This module tests the document ingestion pipeline including loading, parsing,
chunking, embedding, and upsertion to Qdrant.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open
import tempfile
import shutil

from llmaven.agentic.ingestion.pipeline import IngestionPipeline
from llmaven.agentic.exceptions import IngestionError, EmbeddingError
from llmaven.agentic.vector_store.qdrant_manager import QdrantManager


class TestIngestionPipelineInitialization:
    """Test IngestionPipeline initialization."""

    def test_init_with_default_config(self):
        """Test initialization with default config."""
        mock_qdrant_manager = MagicMock()
        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            pipeline = IngestionPipeline()
            assert pipeline.qdrant_manager is not None
            assert pipeline.collection_name == "agentic-rag"

    def test_init_with_custom_collection(self):
        """Test initialization with custom collection name."""
        mock_qdrant_manager = MagicMock()
        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            pipeline = IngestionPipeline(collection_name="custom-collection")
            assert pipeline.collection_name == "custom-collection"


class TestIngestionPipelineLoad:
    """Test document loading functionality."""

    def test_load_from_directory(self):
        """Test loading documents from a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            test_dir = Path(tmpdir)
            (test_dir / "doc1.txt").write_text("Test document 1")
            (test_dir / "doc2.md").write_text("# Test document 2")
            (test_dir / "doc3.pdf").write_text("PDF content")  # Mock PDF
            (test_dir / "ignore.py").write_text("Python file")  # Should be ignored

            mock_qdrant_manager = MagicMock()
            with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
                pipeline = IngestionPipeline()
                documents = pipeline.load([str(test_dir)])

                # Should find text and markdown files, but not Python files
                assert len(documents) >= 2
                file_paths = [doc.get("file_path", "") for doc in documents]
                assert any("doc1.txt" in path for path in file_paths)
                assert any("doc2.md" in path for path in file_paths)

    def test_load_from_multiple_directories(self):
        """Test loading from multiple directories."""
        with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
            test_dir1 = Path(tmpdir1)
            test_dir2 = Path(tmpdir2)
            (test_dir1 / "doc1.txt").write_text("Document 1")
            (test_dir2 / "doc2.txt").write_text("Document 2")

            mock_qdrant_manager = MagicMock()
            with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
                pipeline = IngestionPipeline()
                documents = pipeline.load([str(test_dir1), str(test_dir2)])

                assert len(documents) == 2

    def test_load_nonexistent_directory(self):
        """Test loading from nonexistent directory raises error."""
        mock_qdrant_manager = MagicMock()
        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            pipeline = IngestionPipeline()
            with pytest.raises(IngestionError):
                pipeline.load(["/nonexistent/path"])


class TestIngestionPipelineParse:
    """Test document parsing functionality."""

    def test_parse_text_file(self):
        """Test parsing a plain text file."""
        mock_qdrant_manager = MagicMock()
        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            pipeline = IngestionPipeline()

            doc = {
                "file_path": "test.txt",
                "content": "This is a test document with multiple sentences. Here is another sentence.",
            }

            parsed = pipeline.parse(doc)
            assert parsed["text"] == doc["content"]
            assert parsed["file_path"] == "test.txt"

    def test_parse_markdown_file(self):
        """Test parsing a markdown file."""
        mock_qdrant_manager = MagicMock()
        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            pipeline = IngestionPipeline()

            doc = {
                "file_path": "test.md",
                "content": "# Heading\n\nParagraph text.",
            }

            parsed = pipeline.parse(doc)
            assert "text" in parsed
            assert parsed["file_path"] == "test.md"

    @patch("docling.document_converter.DocumentConverter")
    def test_parse_pdf_with_docling(self, mock_converter):
        """Test parsing PDF with docling."""
        mock_qdrant_manager = MagicMock()
        mock_converter_instance = MagicMock()
        mock_converter.return_value = mock_converter_instance

        # Mock docling output
        mock_doc = MagicMock()
        mock_doc.document.export_to_dict.return_value = {
            "content": [{"text": "PDF content"}],
            "meta": {"heading_hierarchy": ["# Title"]},
        }
        mock_converter_instance.convert.return_value = mock_doc

        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            pipeline = IngestionPipeline()

            doc = {
                "file_path": "test.pdf",
                "content": b"PDF bytes",
            }

            parsed = pipeline.parse(doc)
            assert "text" in parsed
            assert parsed["file_path"] == "test.pdf"

    @patch("docling.document_converter.DocumentConverter")
    def test_parse_fallback_on_docling_error(self, mock_converter):
        """Test that parsing falls back to PyMuPDF if docling fails."""
        mock_qdrant_manager = MagicMock()
        mock_converter.side_effect = Exception("Docling failed")

        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            # Mock fitz import by patching sys.modules before the import happens
            import sys
            mock_fitz = MagicMock()
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_page.get_text.return_value = "PDF text content"
            mock_doc.__iter__ = lambda self: iter([mock_page])
            mock_doc.__enter__ = lambda self: self
            mock_doc.__exit__ = lambda self, *args: None
            mock_fitz.open.return_value = mock_doc
            sys.modules["fitz"] = mock_fitz

            try:
                pipeline = IngestionPipeline()

                doc = {
                    "file_path": "test.pdf",
                    "content": b"PDF bytes",
                }

                parsed = pipeline.parse(doc)
                assert "text" in parsed
                assert "PDF text content" in parsed["text"]
            finally:
                # Clean up
                if "fitz" in sys.modules and sys.modules["fitz"] is mock_fitz:
                    del sys.modules["fitz"]


class TestIngestionPipelineChunk:
    """Test document chunking functionality."""

    def test_chunk_simple_text(self):
        """Test chunking simple text."""
        mock_qdrant_manager = MagicMock()
        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            pipeline = IngestionPipeline()

            doc = {
                "text": "Sentence one. Sentence two. Sentence three.",
                "file_path": "test.txt",
            }

            chunks = pipeline.chunk(doc)
            assert len(chunks) > 0
            assert all("text" in chunk for chunk in chunks)
            assert all("file_path" in chunk for chunk in chunks)

    @patch("docling.document_converter.DocumentConverter")
    def test_chunk_with_heading_hierarchy(self, mock_converter):
        """Test chunking preserves heading hierarchy."""
        mock_qdrant_manager = MagicMock()
        mock_converter_instance = MagicMock()
        mock_converter.return_value = mock_converter_instance

        mock_doc = MagicMock()
        mock_doc.document.export_to_dict.return_value = {
            "content": [
                {"text": "Section 1", "heading": {"level": 1}},
                {"text": "Content under section 1"},
            ],
        }
        mock_converter_instance.convert.return_value = mock_doc

        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            pipeline = IngestionPipeline()

            doc = {
                "file_path": "test.md",
                "content": "# Section 1\n\nContent",
            }

            parsed = pipeline.parse(doc)
            chunks = pipeline.chunk(parsed)

            assert len(chunks) > 0
            # Verify heading hierarchy is preserved
            assert any("heading_hierarchy" in chunk for chunk in chunks)


class TestIngestionPipelineEmbed:
    """Test embedding generation."""

    @patch("llmaven.agentic.ingestion.pipeline.TextEmbedding")
    @patch("llmaven.agentic.ingestion.pipeline.SparseTextEmbedding")
    @patch("llmaven.agentic.ingestion.pipeline.LateInteractionTextEmbedding")
    def test_embed_generates_all_three_vectors(self, mock_colbert, mock_sparse, mock_dense):
        """Test that embedding generates dense, sparse, and ColBERT vectors."""
        # Mock embedding models
        mock_dense_instance = MagicMock()
        mock_dense_instance.embed.return_value = [[0.1] * 384]
        mock_dense.return_value = mock_dense_instance

        mock_sparse_instance = MagicMock()
        mock_sparse_instance.embed.return_value = [{"indices": [1], "values": [0.5]}]
        mock_sparse.return_value = mock_sparse_instance

        mock_colbert_instance = MagicMock()
        mock_colbert_instance.embed.return_value = [[[0.1] * 128] * 10]
        mock_colbert.return_value = mock_colbert_instance

        mock_qdrant_manager = MagicMock()
        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            pipeline = IngestionPipeline()

            chunk = {
                "text": "Test chunk",
                "file_path": "test.txt",
            }

            embedded = pipeline.embed(chunk)

            assert "dense" in embedded
            assert "sparse" in embedded
            assert "colbert" in embedded
            assert len(embedded["dense"]) == 384
            assert isinstance(embedded["sparse"], dict)

    def test_embed_error_handling(self):
        """Test that embedding errors are caught and wrapped."""
        mock_qdrant_manager = MagicMock()
        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            with patch("llmaven.agentic.ingestion.pipeline.TextEmbedding") as mock_dense:
                mock_dense.side_effect = Exception("Embedding failed")

                pipeline = IngestionPipeline()
                chunk = {"text": "test", "file_path": "test.txt"}

                with pytest.raises(EmbeddingError):
                    pipeline.embed(chunk)


class TestIngestionPipelineUpsert:
    """Test upsertion to Qdrant."""

    def test_upsert_chunks_to_qdrant(self):
        """Test upserting embedded chunks to Qdrant."""
        mock_qdrant_manager = MagicMock()

        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            pipeline = IngestionPipeline()

            embedded_chunks = [
                {
                    "text": "Chunk 1",
                    "file_path": "test.txt",
                    "dense": [0.1] * 384,
                    "sparse": {"indices": [1], "values": [0.5]},
                    "colbert": [[0.1] * 128] * 5,
                    "chunk_index": 0,
                },
                {
                    "text": "Chunk 2",
                    "file_path": "test.txt",
                    "dense": [0.2] * 384,
                    "sparse": {"indices": [2], "values": [0.6]},
                    "colbert": [[0.2] * 128] * 5,
                    "chunk_index": 1,
                },
            ]

            pipeline.upsert(embedded_chunks)

            # Verify ensure_collection was called
            mock_qdrant_manager.ensure_collection.assert_called_once_with("agentic-rag", force=False)
            # Verify upsert_points was called
            mock_qdrant_manager.upsert_points.assert_called_once()
            points = mock_qdrant_manager.upsert_points.call_args[0][1]
            assert len(points) == 2


class TestIngestionPipelineFullPipeline:
    """Test the complete ingestion pipeline."""

    def test_ingest_complete_workflow(self):
        """Test the complete ingestion workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)
            (test_dir / "doc1.txt").write_text("Test document content here.")

            mock_qdrant_manager = MagicMock()
            with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
                with patch("llmaven.agentic.ingestion.pipeline.TextEmbedding") as mock_dense:
                    with patch("llmaven.agentic.ingestion.pipeline.SparseTextEmbedding") as mock_sparse:
                        with patch("llmaven.agentic.ingestion.pipeline.LateInteractionTextEmbedding") as mock_colbert:
                            # Mock embeddings
                            mock_dense_instance = MagicMock()
                            mock_dense_instance.embed.return_value = [[0.1] * 384]
                            mock_dense.return_value = mock_dense_instance

                            mock_sparse_instance = MagicMock()
                            mock_sparse_instance.embed.return_value = [{"indices": [1], "values": [0.5]}]
                            mock_sparse.return_value = mock_sparse_instance

                            mock_colbert_instance = MagicMock()
                            mock_colbert_instance.embed.return_value = [[[0.1] * 128] * 10]
                            mock_colbert.return_value = mock_colbert_instance

                            pipeline = IngestionPipeline()
                            pipeline.ingest([str(test_dir)])

                            # Verify collection was created
                            mock_qdrant_manager.ensure_collection.assert_called()
                            # Verify points were upserted
                            mock_qdrant_manager.upsert_points.assert_called()

    def test_ingest_with_batch_processing(self):
        """Test ingestion with batch processing for large document sets."""
        mock_qdrant_manager = MagicMock()

        # Create many mock documents
        mock_documents = [
            {"file_path": f"doc{i}.txt", "content": f"Content {i}"}
            for i in range(150)  # More than default batch size
        ]

        with patch("llmaven.agentic.ingestion.pipeline.QdrantManager", return_value=mock_qdrant_manager):
            with patch("llmaven.agentic.ingestion.pipeline.TextEmbedding") as mock_dense:
                with patch("llmaven.agentic.ingestion.pipeline.SparseTextEmbedding") as mock_sparse:
                    with patch("llmaven.agentic.ingestion.pipeline.LateInteractionTextEmbedding") as mock_colbert:
                        # Mock embeddings
                        mock_dense_instance = MagicMock()
                        mock_dense_instance.embed.return_value = [[0.1] * 384]
                        mock_dense.return_value = mock_dense_instance

                        mock_sparse_instance = MagicMock()
                        mock_sparse_instance.embed.return_value = [{"indices": [1], "values": [0.5]}]
                        mock_sparse.return_value = mock_sparse_instance

                        mock_colbert_instance = MagicMock()
                        mock_colbert_instance.embed.return_value = [[[0.1] * 128] * 10]
                        mock_colbert.return_value = mock_colbert_instance

                        pipeline = IngestionPipeline(batch_size=50)

                        # Mock load to return many documents
                        pipeline.load = MagicMock(return_value=mock_documents)

                        pipeline.ingest([])

                        # Verify upsert was called multiple times (batched)
                        assert mock_qdrant_manager.upsert_points.call_count >= 2
