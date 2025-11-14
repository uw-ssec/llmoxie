from __future__ import annotations

import os
from pathlib import Path
from urllib.request import urlretrieve
from transformers import AutoModelForCausalLM, AutoTokenizer,  BitsAndBytesConfig


# Set the base directory for Rubin-RAG
BASE_DIR = Path(__file__).resolve().parent.parent  # Adjust based on your script location
MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)  # Create the directory if it doesn't exist

# Model file names
OLMO_MODEL_FILE = "OLMo-7B-Instruct-Q4_K_M.gguf"
OLMO_2_MODEL_FILE = "olmo-2-1124-7B-instruct-Q4_K_M.gguf"

# Transformer model names
TRANSFORMER_MODEL_NAME = "allenai/OLMo-2-1124-7B-Instruct"  # Adjust if using another model
TRANSFORMER_MODEL_DIR = MODEL_DIR / TRANSFORMER_MODEL_NAME.replace("/", "_")  # Cache in local directory

def download_model(
    model_name: str,
    model_file: str,
    source: str,
    force: bool = False
) -> Path:
    """
    Generalized function to download a model and store it in the model directory.

    Parameters
    ----------
    model_name : str
        Name of the model for display purposes.
    model_file : str
        File name or identifier for the model.
    source : str
        URL or identifier.
    force : bool, optional
        Whether to force download even if the model already exists, by default False.

    Returns
    -------
    pathlib.Path
        Path to the downloaded model.
    """
    model_path = MODEL_DIR / model_file

    if model_path.exists() and not force:
        print(f"{model_name} model already exists at {model_path}")
        return model_path

    print(f"Downloading {model_name} model...")

    if source.startswith("http"):
        # Download from URL
        urlretrieve(source, model_path)
    else:
        raise ValueError("Source must be a valid URL.")

    print(f"{model_name} model cached at {model_path}")
    return model_path


def download_olmo_model(force: bool = False) -> Path:
    """
    Wrapper for downloading the OLMO model from a URL.
    """
    url = f"https://huggingface.co/ssec-uw/OLMo-7B-Instruct-GGUF/resolve/main/{OLMO_MODEL_FILE}"
    return download_model("OLMO", OLMO_MODEL_FILE, url, force)


def download_olmo_2_model(force: bool = False) -> Path:
    """
    Wrapper for downloading the OLMO 2 model from Hugging Face.
    """
    url = f"https://huggingface.co/allenai/OLMo-2-1124-7B-Instruct-GGUF/resolve/main/{OLMO_2_MODEL_FILE}"
    return download_model("OLMO 2", OLMO_2_MODEL_FILE, url, force)

def load_transformer_model(
    model_name: str = TRANSFORMER_MODEL_NAME, 
    force: bool = False, 
    quantization: str = "8bit"  # Options: "8bit" or "4bit"
):
    """
    Loads a transformer-based model with `bitsandbytes` quantization and caches it.

    Parameters
    ----------
    model_name : str
        Hugging Face model name.
    force : bool, optional
        Whether to force re-download, by default False.
    quantization : str, optional
        Whether to load model in "8bit" or "4bit" mode. Default is "8bit".

    Returns
    -------
    model, tokenizer
        Loaded transformer model and tokenizer.
    """

    if TRANSFORMER_MODEL_DIR.exists() and not force:
        print(f"Transformer model {model_name} is already cached at {TRANSFORMER_MODEL_DIR}")
    else:
        print(f"Downloading transformer model {model_name} to {TRANSFORMER_MODEL_DIR}...")

    # Define the quantization config
    if quantization == "8bit":
        quantization_config = BitsAndBytesConfig(load_in_8bit=True)
    elif quantization == "4bit":
        quantization_config = BitsAndBytesConfig(load_in_4bit=True)
    else:
        raise ValueError("Invalid quantization type. Choose '8bit' or '4bit'.")

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=str(MODEL_DIR))

    # Load model with quantization
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        cache_dir=str(MODEL_DIR),
        device_map="auto",
        quantization_config=quantization_config
    )

    print(f"Transformer model {model_name} loaded successfully with {quantization} quantization.")
    return model, tokenizer