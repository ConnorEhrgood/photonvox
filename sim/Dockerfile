# The demo's live simulator (docs/DEMO.md §2): SIPp 3.6.1 (Debian 12's package, as sipp/Dockerfile) and the scheduler that drives it. Built and
# run on LXC 800 only, by scripts/demo-sim.sh, as the compose project vox-demo-sim. No secret in the image: the phones' credentials are mounted.
FROM debian:12.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends sip-tester=1:3.6.1-* && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends python3 tzdata && rm -rf /var/lib/apt/lists/*
LABEL com.photonvox.purpose="demo-sim" com.photonvox.owner="vox-demo-sim"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /sim
COPY scheduler.py scenarios.py traffic.py tone-ulaw.wav /sim/
ENTRYPOINT ["python3", "/sim/scheduler.py"]
