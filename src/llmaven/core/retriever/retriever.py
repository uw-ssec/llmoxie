from pathlib import Path
from langchain_qdrant import Qdrant
from qdrant_client import QdrantClient
from ..embeddings.embedding_model import get_embedding_model
import shutil

class Retriever:
    def __init__(self, model_name: str = None, qdrant_path: str = None, collection_name: str = None):
        """
        Initializes the Retriever class with a model, Qdrant path, and collection name.

        Args:
            model_name (str): Name of the embedding model to use.
            qdrant_path (str, optional): Path where the Qdrant vector store is located or will be created.
            collection_name (str, optional): Name of the Qdrant collection.
            db (Qdrant, optional): Qdrant instance.
        """
        self.model_name = model_name
        self.embedding = get_embedding_model(self.model_name)
        self.qdrant_path = None
        self.collection_name = None
        self.db = None

    def create_vector_store(self, documents: list, collection_name: str = 'temp_collection'):    
        """
        Creates a Qdrant vector store from a list of documents.

        Args:
            documents (list): List of dictionaries with "content" and optional "filename".

        Returns:
            Qdrant: Initialized vector store instance.
        """
        if not documents:
            raise ValueError("No documents provided for vector store creation.")

        # Delete temp_collection before recreating
        if collection_name == "temp_collection":
            try:
                client = QdrantClient(path="data/vector_stores") 
                client.delete_collection(collection_name)
                shutil.rmtree(Path("data/vector_stores") / collection_name, ignore_errors=True)
                print(f"Deleted existing collection '{collection_name}'.")

            except Exception as e:
                print(f"Warning: Could not delete collection '{collection_name}'. Error: {str(e)}")

        print(f"Creating new Qdrant collection '{collection_name}' with {len(documents)} documents using '{self.model_name}'.")

        self.collection_name = collection_name
        self.qdrant_path = Path("data/vector_stores") / collection_name
        self.qdrant_path.mkdir(parents=True, exist_ok=True)

        self.db = Qdrant.from_documents(
            documents=documents,
            embedding=self.embedding,
            path=str(self.qdrant_path),
            collection_name=self.collection_name,
        )
        return self.db

    def get_vector_store(self, qdrant_path: str = None, collection_name: str = None):
        """
        Loads an existing Qdrant vector store.

        Args:
            qdrant_path (str, optional): Path to the existing Qdrant vector store.
            qdrant_collection (str, optional): Name of the collection in Qdrant.

        Returns:
            Qdrant: Loaded vector store instance.
        """
        if qdrant_path:
            self.qdrant_path = Path(qdrant_path) 
        if collection_name:    
            self.collection_name = collection_name

        client = QdrantClient(path=str(self.qdrant_path))
        self.db = Qdrant(client=client, collection_name=self.collection_name, embeddings=self.embedding)
        return self.db

    def retrieve_docs(self, query: str):
        """
        Retrieves relevant documents based on the query.

        Args:
            query (str): The search query.

        Returns:
            list: List of retrieved document objects.
        """
        if self.db is None:
            raise ValueError("Vector store is not initialized. Call create_vector_store() or get_vector_store() first.")

        retriever = self.db.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 2},
        )
        return retriever.invoke(query)

