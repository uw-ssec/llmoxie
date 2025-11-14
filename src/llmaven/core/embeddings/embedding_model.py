import os
from langchain_huggingface import HuggingFaceEmbeddings

def get_embedding_model(model_name: str = None) -> HuggingFaceEmbeddings:
    """
    Returns an instance of an embedding model.
    
    Parameters:
        model_name (str, optional): The name/identifier of the embedding model to use.
            If not provided, the function checks the environment variable 'EMBEDDING_MODEL_NAME'
            and falls back to a default value.
            
    Returns:
        HuggingFaceEmbeddings: An instance of the embedding model.
    """
    # Use the provided model_name, otherwise check environment, then default.
    if model_name is None:
        model_name = os.getenv("EMBEDDING_MODEL_NAME", "intfloat/multilingual-e5-large-instruct")
    return HuggingFaceEmbeddings(model_name=model_name)

if __name__ == "__main__":
    # Quick test to verify that the embedding model loads.
    embedding = get_embedding_model()
    print(f"Using embedding model: {embedding.model_name}")
