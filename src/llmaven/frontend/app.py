import streamlit as st
import requests
import json
import time
from langchain.document_loaders import PyMuPDFLoader
from llmaven.frontend.config import config, expand_query, format_prompt

st.title("RAG Chatbot")

# Initialize session state
st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("chunks"):
            st.markdown("### Retrieved Document Chunks:")
            for chunk in message["chunks"]:
                st.markdown(f"- {chunk}")

# File uploader for documents
uploaded_files = st.file_uploader("Attach documents (PDFs)", type=["pdf"], accept_multiple_files=True)

# Function to process uploaded PDFs
def process_uploaded_files(uploaded_files):
    """Reads uploaded PDF files and extracts text + metadata."""
    documents = []
    for file in uploaded_files:
        with open(file.name, "wb") as f:
            f.write(file.getbuffer())
        loader = PyMuPDFLoader(file.name)  # Load PDF
        pages = loader.load()

        for page in pages:
            documents.append({
                "page_content": page.page_content,
                "metadata": page.metadata
            })

    return documents

# Process PDFs only if uploaded
documents = process_uploaded_files(uploaded_files) if uploaded_files else []

# User input for question
if query := st.chat_input("Your question:"):
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    with st.spinner("Retrieving relevant documents..."):
        try:
            retrieve_payload = {
                "documents": documents,
                "query": expand_query(query),
                "existing_collection": config.existing_collection,
                "existing_qdrant_path": config.existing_qdrant_path,
                "embedding_model": config.embedding_model
            }
            retrieve_response = requests.post(f"{config.api_base_url}/retrieve/", json=retrieve_payload)
            retrieved_docs = retrieve_response.json().get("docs", []) if retrieve_response.status_code == 200 else []
        except Exception as e:
            retrieved_docs = []
            st.error(f"❌ Retrieval API failed: {str(e)}")

    # Show retrieved documents immediately
    retrieved_text = "\n\n".join(doc["page_content"][:500] for doc in retrieved_docs)
    if retrieved_docs:
        with st.chat_message("assistant"):
            st.markdown("### Retrieved Document Chunks:")
            for doc in retrieved_docs:
                st.markdown(f"- {doc['page_content'][:500]}")

    # Generate response using retrieved documents as context
    with st.spinner("Generating response..."):
        try:
            generate_payload = {
                "prompt": format_prompt(retrieved_text, query),
                "generation_model": config.generation_model
            }
            generate_response = requests.post(f"{config.api_base_url}/generate/", json=generate_payload)
            generated_answer = generate_response.json().get("answer", "") if generate_response.status_code == 200 else "⚠️ Failed to generate response."
        except Exception as e:
            generated_answer = "⚠️ Failed to generate response."
            st.error(f"❌ Generation API failed: {str(e)}")

    # Display AI-generated response
    assistant_message = {
        "role": "assistant",
        "content": generated_answer,
        "chunks": [doc["page_content"][:500] for doc in retrieved_docs]
    }
    st.session_state.messages.append(assistant_message)

    with st.chat_message("assistant"):
        st.markdown(generated_answer)
