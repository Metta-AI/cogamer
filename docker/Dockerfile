FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git tmux curl unzip jq openssh-client openssh-server procps sudo && \
    rm -rf /var/lib/apt/lists/*

# Configure sshd
RUN mkdir -p /run/sshd && \
    ssh-keygen -A && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config && \
    sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config

# Node.js (for claude-code bootstrap)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# AWS CLI v2
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip && \
    unzip awscliv2.zip && ./aws/install && rm -rf aws awscliv2.zip

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# uv (Python package manager — needed by Claude Code)
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# cloudflared (Cloudflare Tunnel for dashboard)
RUN curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
    -o /tmp/cloudflared.deb && dpkg -i /tmp/cloudflared.deb && rm /tmp/cloudflared.deb

# Create non-root user with passwordless sudo for sshd
# Make site-packages and bin writable by cogamer so uv can install packages
RUN useradd -m -s /bin/bash cogamer && \
    echo "cogamer ALL=(root) NOPASSWD: /usr/sbin/sshd" >> /etc/sudoers.d/cogamer && \
    find /usr/local -type d -exec chown cogamer:cogamer {} +

# Install cogamer package + cogames CLI as cogamer user
COPY --chown=cogamer:cogamer . /opt/cogamer
USER cogamer
RUN uv pip install --system /opt/cogamer cogames && \
    rm -rf ~/.cache/uv /tmp/uv-*

WORKDIR /home/cogamer
ENV HOME=/home/cogamer

ENV PATH="/home/cogamer/.local/bin:$PATH"

# Claude Code CLI — native installer (user-writable, supports auto-updates)
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "cogamer.entrypoint"]
