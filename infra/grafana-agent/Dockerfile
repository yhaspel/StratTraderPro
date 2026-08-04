# Grafana Agent (the static, YAML-configured collector). Pinned to a stable
# release tag rather than `:latest` so a Railway redeploy can't surprise us
# with a config-format change.
FROM grafana/agent:v0.43.4

# Bake the config in. Substitution of ${ENV_VAR} placeholders happens at
# container start because of the -config.expand-env flag below.
COPY agent.yaml /etc/agent/agent.yaml

# Default WAL location (override with AGENT_WAL_DIR if you ever attach a volume)
ENV AGENT_WAL_DIR=/tmp/agent-wal

# Railway expects the container to listen on $PORT for healthchecks; the agent's
# built-in HTTP server lives on 12345 by default. Bind it to $PORT so Railway's
# probe can hit /-/ready on it.
EXPOSE 12345

# In v0.40+ the static-mode binary was renamed `/bin/agent` → `/bin/grafana-agent`
# (the old name now belongs to Grafana Alloy). We override the upstream ENTRYPOINT
# so this Dockerfile is pinned to the static-mode entrypoint regardless of any
# image-default changes Grafana might make in future patch releases.
ENTRYPOINT ["/bin/grafana-agent"]
CMD ["-config.file=/etc/agent/agent.yaml", \
     "-config.expand-env=true", \
     "-server.http.address=0.0.0.0:12345", \
     "-metrics.wal-directory=/tmp/agent-wal"]
