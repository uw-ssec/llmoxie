FROM mcr.microsoft.com/devcontainers/base:jammy

ARG PIXI_VERSION=v0.55.0
ARG NODE_MAJOR=22

# Install pixi binary
RUN curl -L -o /usr/local/bin/pixi -fsSL --compressed \
    "https://github.com/prefix-dev/pixi/releases/download/${PIXI_VERSION}/pixi-$(uname -m)-unknown-linux-musl" \
    && chmod +x /usr/local/bin/pixi

# Install Node.js LTS (for Claude Code)
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code

# Copy project files needed for pixi install and set ownership
RUN mkdir -p /workspaces/llmaven && chown vscode:vscode /workspaces/llmaven
WORKDIR /workspaces/llmaven
COPY --chown=vscode:vscode pixi.toml pixi.lock pyproject.toml LICENSE README.md ./
COPY --chown=vscode:vscode src/llmaven/__init__.py src/llmaven/__init__.py

# Switch to vscode user BEFORE pixi install so .pixi is owned correctly
# from the start, avoiding a costly chown layer that duplicates the env
USER vscode

# Pre-install pixi environment (the expensive step, now cached in image)
# Clean up caches in the same layer to keep image small
RUN pixi install -e demo \
    && pixi clean cache --yes \
    && rm -rf /home/vscode/.cache/rattler

# Install Pulumi CLI and remove unused language runtimes (keep only Python)
RUN pixi run -e demo install-pulumi \
    && rm -f .pixi/envs/demo/bin/pulumi-language-dotnet \
             .pixi/envs/demo/bin/pulumi-language-go \
             .pixi/envs/demo/bin/pulumi-language-java \
             .pixi/envs/demo/bin/pulumi-language-nodejs \
             .pixi/envs/demo/bin/pulumi-language-yaml

# Configure user environment
ENV VSCODE_HOME=/home/vscode SHELL=/bin/bash
WORKDIR ${VSCODE_HOME}
RUN echo 'eval "$(pixi completion -s bash)"' >> ${VSCODE_HOME}/.bashrc
