from langchain.schema import Document
from ..core.retriever.retriever import Retriever

def json_to_document(json_data):
    """Convert JSON dict to LangChain Document object."""
    return Document(
        page_content=json_data["page_content"],
        metadata=json_data["metadata"]
    )

def perform_retrieval(documents, query, existing_collection, existing_qdrant_path, embedding_model):
    # Convert each JSON document to a LangChain Document object
    if documents:
        docs = [json_to_document(doc) for doc in documents]
    
    # Instantiate the retriever with the provided embedding model
    retriever = Retriever(model_name=embedding_model)
    
    # Create a vector store and retrieve relevant documents
    if documents:
        retriever.create_vector_store(docs, collection_name="temp_collection")
    elif existing_collection and existing_qdrant_path:
        retriever.get_vector_store(qdrant_path=existing_qdrant_path, collection_name=existing_collection)
    else:
        raise ValueError("No documents or existing vector store provided.")
    relevant_docs = retriever.retrieve_docs(query)
    
    # Format the response with a limited preview of page content
    response_data = [
        {
            "metadata": doc.metadata,
            "page_content": doc.page_content[:500]  # Limit preview size
        }
        for doc in relevant_docs
    ]
    
    return {"docs": response_data, "status_code": 200}