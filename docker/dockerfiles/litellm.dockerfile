# Pinned by digest: tag v1.108.6 (signed upstream release).
FROM ghcr.io/berriai/litellm:v1.108.6@sha256:c64fe10f82a1f77906f88574f954317c50f67c617e0c97b70ac8fc61b74d3ec3 AS litellm

# Since v1.106.x the image ships a uv-built venv with no pip executable, but the
# bundled ensurepip works. Re-pinning litellm makes the build fail instead of
# letting mlflow's dependencies silently replace the verified litellm package.
# mlflow-skinny covers the LiteLLM mlflow callback; full mlflow caps
# cryptography<47 and would downgrade the base image's patched cryptography.
RUN python -m ensurepip \
 && python -m pip install --no-cache-dir \
      "litellm==1.108.6" "mlflow-skinny==3.6.0" "azure-storage-blob>=12.0.0,<13" "azure-identity>=1.0.0,<2"

# Opt-in variant (--target litellm-dlp) with the ceil-dlp guardrail
# (https://github.com/uw-ssec/ceil-dlp). Its guardrail mode exists only on the
# uw-ssec fork, so it is pinned to a commit rather than the PyPI release.
# ceil-dlp imports its OCR detectors at load time, which need PyTorch: install
# the CPU-only wheels first so pip does not pull the multi-GB CUDA build;
# torchvision must match torch exactly (0.29.x is built for 2.14). The
# PyTorch index brings setuptools 78.1.0 (CVE-2025-47273); require >=78.1.1.
# Packages already in the image are held at their versions with a constraints
# file; unconstrained, pip moved protobuf to 7 and ml-dtypes to 0.6, breaking
# mlflow-skinny, grpcio-status and redisvl. Only huggingface-hub and tokenizers
# may move: gliner and transformers 4.x need huggingface-hub<1, and the older
# versions still satisfy litellm (hub>=0.34, tokenizers>=0.21).
# python-doctr and presidio-image-redactor require opencv-python, which needs
# X11 libraries the image lacks (libxcb); it is swapped for the headless build
# of the same version, which provides the same cv2 module. pip check then lists
# opencv-python as missing for those two; that is expected. sentencepiece 0.2.3
# (from gliner) ships protobuf-7 generated code that fails on the base image's
# protobuf 5.29.6 at request time; 0.2.2 works with it.
FROM litellm AS litellm-dlp

RUN python -c "import importlib.metadata as m; print('\n'.join(sorted({d.metadata['Name'] + '==' + d.version for d in m.distributions() if d.metadata['Name'].lower().replace('_', '-') not in ('huggingface-hub', 'tokenizers')})))" > /tmp/base-constraints.txt \
 && python -m pip install --no-cache-dir -c /tmp/base-constraints.txt \
      --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1" "torchvision==0.29.1" \
 && python -m pip install --no-cache-dir -c /tmp/base-constraints.txt \
      "litellm==1.108.6" "torch==2.14.1" "torchvision==0.29.1" "setuptools>=78.1.1" \
      "sentencepiece==0.2.2" \
      "ceil-dlp @ https://github.com/uw-ssec/ceil-dlp/archive/abad0ee02b869144cc97b5ed5b78dcf6d04cf9b1.tar.gz" \
      "en_core_web_lg @ https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl" \
 && v=$(python -c "import importlib.metadata as m; print(m.version('opencv-python'))") \
 && python -m pip uninstall -y opencv-python \
 && python -m pip install --no-cache-dir --no-deps "opencv-python-headless==$v" \
 && rm /tmp/base-constraints.txt

# The plain image stays the default build target.
FROM litellm
