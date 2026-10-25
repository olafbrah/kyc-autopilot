import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEV_JWT_SECRET, DEV_AGENT_SECRET = "dev-only-secret-change-me", "dev-agent-secret"


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./kyc.db"))
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", DEV_JWT_SECRET))
    dev_login: bool = field(default_factory=lambda: os.getenv("DEV_LOGIN", "1") == "1")
    # client_id=secret pairs for service identities (OAuth client credentials)
    service_clients: dict = field(default_factory=lambda: dict(
        p.split("=", 1) for p in os.getenv("SERVICE_CLIENTS", f"svc-kyc-agent={DEV_AGENT_SECRET}").split(",") if p))
    policy_path: Path = field(default_factory=lambda: Path(os.getenv("POLICY_PATH", ROOT / "policy.yaml")))
    evals_dir: Path = field(default_factory=lambda: Path(os.getenv("EVALS_DIR", ROOT.parent / "evals")))
    frontend_dist: Path = field(default_factory=lambda: Path(os.getenv("FRONTEND_DIST", ROOT.parent.parent / "frontend" / "dist")))
    seed_demo: int = field(default_factory=lambda: int(os.getenv("SEED_DEMO", "0")))
    cookie_secure: bool = field(default_factory=lambda: os.getenv("COOKIE_SECURE", "0") == "1")
    job_lease_seconds: int = 120

    def __post_init__(self):
        if not self.dev_login and (self.jwt_secret == DEV_JWT_SECRET or DEV_AGENT_SECRET in self.service_clients.values()):
            raise RuntimeError("JWT_SECRET and SERVICE_CLIENTS must be set when DEV_LOGIN=0")
