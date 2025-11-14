import os
from langchain_huggingface import HuggingFaceEmbeddings
import logging


class EmbeddingModel():
    def __init__(self, 
                 model_name, 
                 model_path_prefix = None):
        
        self.model_name = model_name
        self.cache_path = os.path.join(os.path.dirname(__file__), "model_cache")
        if not os.path.exists(self.cache_path):
            os.makedirs(self.cache_path)
            os.makedirs(os.path.join(self.cache_path, "embeddings"))
        self.model_path = os.path.join(self.cache_path, "embeddings", model_path_prefix) if model_path_prefix else None
        self.embeddings = None
        pass 
    
    def load_embedding_model(self, model_path=None, download_model = True):
            embeddings = HuggingFaceEmbeddings(
                model_name=self.model_path_prefix, 
                cache_folder = os.path.join(self.cache_path, "embeddings"), 
                model_kwargs={"local_files_only": True}
                )
            self.embeddings = embeddings
    
    def download_embedding_model(self, model_name,):
            embeddings = HuggingFaceEmbeddings(
                 model_name=self.model_name, 
                 cache_folder = os.path.join(self.cache_path, "embeddings")
                 )
            self.embeddings = embeddings

    def get_embedding_model(self, model_name, model_path = None, download_model = False):
        if model_path and os.path.exists(model_path.exists):
            logging.info(f"{model_name} exists at {model_path}")
            try:
                self.load_embedding_model(model_name, model_path)
            except: 
                 logging.info(f"{model_name} model failed to load from {model_path}.")
        elif download_model:
            try:
                self.download_embedding_model(model_name)
            except:
                logging.info(f"{model_name} model failed to download.")
