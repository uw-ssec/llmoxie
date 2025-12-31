# Troubleshooting Guide

Common issues and solutions for LLMaven development.

---

## Vector Database Issues

### Collection Not Found

**Symptom**: `Collection not found` error when querying Qdrant.

**Diagnosis**:

```python
from qdrant_client import QdrantClient

client = QdrantClient(path="path/to/qdrant")
print([c.name for c in client.get_collections().collections])
```

**Common Causes**:
- Wrong collection name
- Incorrect Qdrant path
- Collection not yet created

**Solution**: Verify the collection exists and the path matches your configuration.

---

## Model Issues

### CUDA Out of Memory

**Symptom**: `CUDA out of memory` error during model loading or inference.

**Solution**: Use quantization to reduce memory usage:

```python
model.load_language_model(quantization="4bit")  # or "8bit"
```

**Alternative**: Use a smaller model or offload to CPU.

---

## API Issues

### Server Won't Start

**Symptom**: FastAPI server fails to start.

**Diagnosis**:

```bash
llmaven server serve --env development --reload
```

Check for:
- Port 8000 already in use (`lsof -i :8000`)
- Missing environment variables
- Import errors in modules

---

## Environment Issues

### Pixi Environment Problems

**Symptom**: Packages not found or wrong versions.

**Solution**:

```bash
# Clean reinstall
pixi clean
pixi install

# Verify environment
pixi shell -e llmaven
python -c "import llmaven; print(llmaven.__version__)"
```
