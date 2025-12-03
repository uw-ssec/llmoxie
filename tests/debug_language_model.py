import logging
import os
from llmaven.core.generator.language_model import LanguageModel

# Enable Hugging Face logs
import transformers
transformers.utils.logging.set_verbosity_info()  # Ensures logs appear

# Set logging level
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def test_language_model():
    logging.info("🚀 Starting LanguageModel Debugging...")

    model_name = "allenai/OLMo-2-1124-7B-Instruct"  # Change this to your actual model name
    cache_path = os.path.join(os.path.dirname(__file__), "../models")
    model_path = os.path.join(cache_path, model_name.replace("/", "_"))

    logging.info(f"📂 Model cache path: {model_path}")

    # Initialize model
    try:
        logging.info("🟡 Initializing LanguageModel...")
        model = LanguageModel(model_name=model_name)
        logging.info("✅ LanguageModel initialized successfully.")
    except Exception as e:
        logging.error(f"❌ Error initializing LanguageModel: {e}")
        return

    # Load model with quantization
    try:
        logging.info("🟡 Loading language model with 8-bit quantization...")
        model.load_language_model(quantization="8bit")
        logging.info("✅ Model loaded successfully.")
    except Exception as e:
        logging.error(f"❌ Error loading model: {e}")
        return

    # Load Hugging Face pipeline
    try:
        logging.info("🟡 Loading Hugging Face pipeline...")
        model.load_hg_pipeline()
        logging.info("✅ Pipeline loaded successfully.")
    except Exception as e:
        logging.error(f"❌ Error loading pipeline: {e}")
        return

    # Run inference test
    prompt = "Tell me a fun fact about space."
    try:
        logging.info(f"🟡 Running inference on prompt: {prompt}")
        response = model.inference(prompt)
        logging.info(f"✅ Inference completed successfully.\nResponse: {response}")
    except Exception as e:
        logging.error(f"❌ Error during inference: {e}")
        return

if __name__ == "__main__":
    test_language_model()
