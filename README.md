# LLMaven

This project's scientific goal is to create open, transparent and useful
AI-based software for scientific research. We propose building a tool library,
named LLMaven, using a Generative AI approach, specifically Retrieval Augmented
Generation (RAG) based LLM. We will use RAG as a means of extending LLMs for
data that has privacy/IP concerns that is cost effective for individual
researchers who do not have the resources to develop their own models (or
purchase expensive equipment). LLMaven will leverage publicly available diverse
datasets and disparate academic knowledge bases.

## Running LLMaven

Pre-requisites:

- Install Pixi (`curl -fsSL https://pixi.sh/install.sh | bash`)
- Create the vector database by running the
  [Quadrant Database Creation Notebook](https://github.com/uw-ssec/tutorials/blob/main/Archive/SciPy2024/appendix/qdrant-vector-database-creation.ipynb)
- Run: `pixi install`

- Start the interactive chat application:

```sh
pixi run serve-panel
```

And open a browser at http://localhost:5006

## Debugging

To run in the debugger:

- Set your python interpreter to `.pixi/envs/default/bin/python`
  (`Cmd+Shift+P: Python Interpreter`)
- Open `legacy/rubin-panel-app.py`
- Run and Debug (F5)
