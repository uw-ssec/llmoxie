import os
from pathlib import Path
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import Qdrant
from qdrant_client import QdrantClient

# Configurations
PDF_FOLDER_PATH = Path("/workspaces/Rubin-RAG-exp/data/raw/Rubin")
QDRANT_PATH = Path("/workspaces/Rubin-RAG-exp/data/vector_stores/rubin_qdrant_exp")
QDRANT_COLLECTION = "rubin_telescope_exp"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L12-v2"  # Change this to try new models
# EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-large-instruct"

def load_documents(pdf_folder: Path):
    """Loads PDFs from a given folder and extracts text."""
    documents = []
    for file in pdf_folder.glob("*.pdf"):
        loader = PyMuPDFLoader(str(file))
        documents.extend(loader.load())
    return documents

def initialize_qdrant(documents, model_name: str, qdrant_path: Path, collection_name: str):
    """Initializes Qdrant with specified embedding model and loads documents."""
    embedding = HuggingFaceEmbeddings(model_name=model_name)

    # if qdrant_path.exists():
    #     print(f"Qdrant collection '{collection_name}' already exists at {qdrant_path}, loading it.")
    #     client = QdrantClient(path=str(qdrant_path))
    #     return Qdrant(client=client, collection_name=collection_name, embeddings=embedding)

    print(f"Creating new Qdrant collection '{collection_name}' with {len(documents)} documents using '{model_name}'.")
    
    qdrant_path.mkdir(parents=True, exist_ok=True)
    return Qdrant.from_documents(
        documents=documents,
        embedding=embedding,
        path=str(qdrant_path),
        collection_name=collection_name,
    )

# Load documents
documents = load_documents(PDF_FOLDER_PATH)

# Initialize Qdrant
qdrant = initialize_qdrant(documents, EMBEDDING_MODEL_NAME, QDRANT_PATH, QDRANT_COLLECTION)

# Check stored vectors
print(f"Number of vectors stored: {qdrant.client.count(collection_name=QDRANT_COLLECTION)}")
