# RAG Evaluation

Making this PR just for an initial reference.

## **Execution Order**
The scripts should be run in the following order:

1. **`trulens_eval.ipynb`** - This script sets up the RAG pipeline, retrieves context from Qdrant, and evaluates responses using TruLens.
2. **`cosine-similarity_eval.ipynb`** - Computes cosine similarity between the question, context, generated responses and ground truth answers.
3. **`deepEval_eval.ipynb`** - Runs DeepEval to assess various metrics.

