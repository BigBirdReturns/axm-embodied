from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

def verify_ed25519(public_key_bytes: bytes, message: bytes, signature: bytes) -> bool:
    vk = VerifyKey(public_key_bytes)
    try:
        vk.verify(message, signature)
        return True
    except BadSignatureError:
        return False
