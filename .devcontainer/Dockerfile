# ARG PIXI_TAG=0.38.0-noble
# FROM ghcr.io/prefix-dev/pixi:$PIXI_TAG

# Use NVIDIA's official CUDA runtime image (CUDA 12.4 + cuDNN)
FROM nvidia/cuda:12.6.3-devel-ubuntu24.04

# # Specify arg again here
# ARG PIXI_TAG

# Install basic apt packages
RUN echo "Installing Apt-get packages..." \
    && apt-get update --fix-missing > /dev/null \
    && apt-get install -y wget zip tzdata curl git ca-certificates > /dev/null \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Pixi manually
RUN curl -fsSL https://pixi.sh/install.sh | bash

# # Ensure NVIDIA runtime support is available
# RUN echo "Installing NVIDIA Container Toolkit requirements..." \
#     && apt-get update && apt-get install -y nvidia-container-toolkit nvidia-cuda-toolkit

# Install Docker
# Add Docker's official GPG key:
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources
RUN echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    tee /etc/apt/sources.list.d/docker.list > /dev/null

RUN echo "Install docker" \
    && apt-get update > /dev/null \
    && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Add runtime as NVIDIA for GPU access
ENV PATH="/usr/local/cuda/bin:${PATH}"
ENV LD_LIBRARY_PATH="/usr/local/cuda/lib64:${LD_LIBRARY_PATH}"
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Expose Streamlit port
EXPOSE 8501
