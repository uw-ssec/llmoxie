from ..core.generator.language_model import LanguageModel


# Global model instance (lazy-loaded)
MODEL_INSTANCES = {}

def get_model(generation_model):
    """
    Retrieve or create a cached instance of the language model.
    """
    
    if generation_model not in MODEL_INSTANCES:

        MODEL_INSTANCES[generation_model] = LanguageModel(model_name=generation_model)
        MODEL_INSTANCES[generation_model].load_language_model(quantization="8bit")
        MODEL_INSTANCES[generation_model].load_hg_pipeline()
    return MODEL_INSTANCES[generation_model]

def generate_answer(prompt, generation_model):
    model = get_model(generation_model)
    response = model.inference(prompt)
    return {"answer": response, "status_code": 200} 
