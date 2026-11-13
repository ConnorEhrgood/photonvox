"""photonid_directory_client: the reference client for the PhotonID directory. Vendor this folder into your product (pure Python, needs httpx)."""
from .client import AuthError, Change, DirectoryClient, DirectoryError, Resolved, SyncResult
from .notice import NoticeError, sign_notice, verify_notice
from .projection import KINDS, Projection

__all__ = ["AuthError", "Change", "DirectoryClient", "DirectoryError", "KINDS", "NoticeError", "Projection", "Resolved", "SyncResult", "sign_notice", "verify_notice"]
__version__ = "1.0.0"
