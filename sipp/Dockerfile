# SIPp for PhotonVox's engine tests: the "upstream" that plays every carrier, and simulated phones. Built and run on LXC 800 only, by
# scripts/sipp.sh. SIPp 3.6.1, Debian 12's package.
FROM debian:12.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends sip-tester=1:3.6.1-* && rm -rf /var/lib/apt/lists/*
LABEL com.photonvox.purpose="sipp" com.photonvox.owner="photonvox-tests"
WORKDIR /scenarios
COPY scenarios/ /scenarios/
ENTRYPOINT ["sipp"]
