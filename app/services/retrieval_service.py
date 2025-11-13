from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from core.retriever.retriever import Retriever

TEXT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
)

def json_to_document(json_data):
    """Convert JSON dict to chunked LangChain Document objects."""
    text = json_data.get("page_content", "")
    if not text:
        return []

    base_metadata = dict(json_data.get("metadata") or {})
    documents = []

    for idx, chunk in enumerate(TEXT_SPLITTER.split_text(text)):
        metadata = base_metadata.copy()
        metadata["chunk_index"] = idx
        documents.append(Document(page_content=chunk, metadata=metadata))

    return documents

def perform_retrieval(documents, query, existing_collection, existing_qdrant_path, embedding_model):
    # Convert each JSON document to a LangChain Document object
    if documents:
        docs = []
        for doc in documents:
            docs.extend(json_to_document(doc))
        if not docs:
            raise ValueError("Document payload did not yield any text chunks for retrieval.")
    
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