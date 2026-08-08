"""Tests for agentcrawl.utils.crypto module."""

import base64
import hashlib
import hmac
import os
from unittest.mock import patch

import pytest

from agentcrawl.utils.crypto import (
    CryptoManager,
    b64_decode,
    b64_decode_bytes,
    b64_encode,
    b64_encode_bytes,
    decrypt_api_key,
    derive_key,
    encrypt_api_key,
    generate_api_key,
    generate_job_id,
    generate_request_id,
    generate_session_id,
    generate_token,
    hash_sha256,
    hash_sha512,
    hash_url,
    hmac_sign,
    hmac_verify,
    mask_api_key,
    mask_email,
)


class TestHashing:
    """Tests for hash functions."""

    def test_hash_sha256_string(self):
        result = hash_sha256("hello world")
        assert result == hashlib.sha256(b"hello world").hexdigest()
        assert len(result) == 64

    def test_hash_sha256_bytes(self):
        result = hash_sha256(b"hello world")
        assert result == hashlib.sha256(b"hello world").hexdigest()

    def test_hash_sha256_deterministic(self):
        assert hash_sha256("test") == hash_sha256("test")

    def test_hash_sha256_different_inputs(self):
        assert hash_sha256("a") != hash_sha256("b")

    def test_hash_sha512_string(self):
        result = hash_sha512("hello world")
        assert result == hashlib.sha512(b"hello world").hexdigest()
        assert len(result) == 128

    def test_hash_sha512_bytes(self):
        result = hash_sha512(b"hello world")
        assert result == hashlib.sha512(b"hello world").hexdigest()

    def test_hash_url(self):
        url = "https://example.com/page/"
        result = hash_url(url)
        expected = hash_sha256("https://example.com/page")
        assert result == expected

    def test_hash_url_no_trailing_slash(self):
        result = hash_url("https://example.com/page")
        assert result == hash_sha256("https://example.com/page")


class TestHmac:
    """Tests for HMAC functions."""

    def test_hmac_sign_string(self):
        result = hmac_sign("message", "key")
        expected = hmac.new(b"key", b"message", hashlib.sha256).hexdigest()
        assert result == expected

    def test_hmac_sign_bytes(self):
        result = hmac_sign(b"message", b"key")
        expected = hmac.new(b"key", b"message", hashlib.sha256).hexdigest()
        assert result == expected

    def test_hmac_sign_mixed_types(self):
        result = hmac_sign("message", b"key")
        assert result is not None

    def test_hmac_sign_sha512(self):
        result = hmac_sign("message", "key", algorithm="sha512")
        expected = hmac.new(b"key", b"message", hashlib.sha512).hexdigest()
        assert result == expected

    def test_hmac_sign_md5(self):
        result = hmac_sign("message", "key", algorithm="md5")
        expected = hmac.new(b"key", b"message", hashlib.md5).hexdigest()
        assert result == expected

    def test_hmac_sign_invalid_algorithm_fallback(self):
        # Invalid algorithm falls back to sha256
        result = hmac_sign("message", "key", algorithm="invalid")
        expected = hmac.new(b"key", b"message", hashlib.sha256).hexdigest()
        assert result == expected

    def test_hmac_verify_valid(self):
        sig = hmac_sign("message", "key")
        assert hmac_verify("message", sig, "key") is True

    def test_hmac_verify_invalid(self):
        sig = hmac_sign("message", "key")
        assert hmac_verify("message", sig, "wrong-key") is False

    def test_hmac_verify_different_data(self):
        sig = hmac_sign("message", "key")
        assert hmac_verify("other", sig, "key") is False


class TestTokenGeneration:
    """Tests for token generation functions."""

    def test_generate_token_default(self):
        token = generate_token(32)
        assert len(token) == 32

    def test_generate_token_with_prefix(self):
        token = generate_token(10, prefix="agc_")
        assert token.startswith("agc_")
        assert len(token) == 14  # 3 + 10 + 1

    def test_generate_token_unique(self):
        tokens = {generate_token(32) for _ in range(100)}
        assert len(tokens) == 100

    def test_generate_api_key(self):
        key = generate_api_key()
        assert key.startswith("agc_live_")

    def test_generate_api_key_custom_prefix(self):
        key = generate_api_key(prefix="my")
        assert key.startswith("my_live_")

    def test_generate_request_id(self):
        rid = generate_request_id()
        assert rid.startswith("req_")
        assert len(rid) == 16  # "req_" + 12 hex chars

    def test_generate_request_id_unique(self):
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100

    def test_generate_job_id(self):
        jid = generate_job_id()
        assert jid.startswith("job_")
        assert len(jid) == 16  # "job_" + 12 hex chars

    def test_generate_session_id(self):
        sid = generate_session_id()
        assert sid.startswith("sess_")
        assert len(sid) == 21  # "sess_" + 16 hex chars

    def test_generate_token_min_length(self):
        token = generate_token(1)
        assert len(token) >= 1


class TestDeriveKey:
    """Tests for key derivation."""

    def test_derive_key_basic(self):
        key, salt = derive_key("password")
        assert len(key) == 32
        assert len(salt) == 16

    def test_derive_key_deterministic_with_salt(self):
        key1, _salt = derive_key("password", salt=b"fixed_salt_12345678")
        key2, _ = derive_key("password", salt=b"fixed_salt_12345678")
        assert key1 == key2

    def test_derive_key_different_passwords(self):
        key1, _ = derive_key("password1")
        key2, _ = derive_key("password2")
        assert key1 != key2

    def test_derive_key_custom_length(self):
        key, _ = derive_key("password", key_length=64)
        assert len(key) == 64

    def test_derive_key_custom_iterations(self):
        key, _ = derive_key("password", iterations=1000)
        assert len(key) == 32


class TestBase64:
    """Tests for base64 utilities."""

    def test_b64_encode_string(self):
        result = b64_encode("hello")
        assert result == base64.b64encode(b"hello").decode("ascii")

    def test_b64_encode_bytes(self):
        result = b64_encode(b"hello")
        assert result == base64.b64encode(b"hello").decode("ascii")

    def test_b64_decode(self):
        encoded = base64.b64encode(b"hello").decode("ascii")
        assert b64_decode(encoded) == "hello"

    def test_b64_encode_bytes_func(self):
        result = b64_encode_bytes(b"hello")
        assert result == base64.b64encode(b"hello").decode("ascii")

    def test_b64_decode_bytes(self):
        encoded = base64.b64encode(b"hello").decode("ascii")
        assert b64_decode_bytes(encoded) == b"hello"


class TestMasking:
    """Tests for masking functions."""

    def test_mask_api_key_normal(self):
        result = mask_api_key("sk-abcdef123456")
        assert "..." in result
        assert "sk-" in result
        assert "3456" in result

    def test_mask_api_key_short(self):
        # "short" has 5 chars, visible_chars=4, so it's not <= 4
        # prefix is empty (len <= 6), suffix = "hort"
        result = mask_api_key("short")
        assert result == "...hort"

    def test_mask_api_key_very_short(self):
        # Key with length <= visible_chars returns all asterisks
        result = mask_api_key("ab", visible_chars=4)
        assert result == "**"

    def test_mask_api_key_exact_length(self):
        # "abcd" has 4 chars, visible_chars=4, so len <= visible_chars
        result = mask_api_key("abcd")
        assert result == "****"

    def test_mask_api_key_empty(self):
        assert mask_api_key("") == ""

    def test_mask_api_key_custom_visible(self):
        result = mask_api_key("sk-abcdef123456", visible_chars=6)
        assert "3456" in result
        assert len(result) > 6

    def test_mask_email_normal(self):
        result = mask_email("user@example.com")
        assert result == "u***@example.com"

    def test_mask_email_short_local(self):
        result = mask_email("a@example.com")
        assert result == "*@example.com"

    def test_mask_email_no_at(self):
        assert mask_email("noemail") == "***"


class TestCryptoManager:
    """Tests for CryptoManager class."""

    @pytest.fixture
    def manager(self):
        key = CryptoManager.generate_encryption_key()
        return CryptoManager(encryption_key=key)

    def test_creation(self, manager):
        assert manager is not None
        assert manager._encryption_key is not None

    def test_repr(self, manager):
        repr_str = repr(manager)
        assert "CryptoManager" in repr_str
        assert "***" in repr_str

    def test_encrypt_decrypt_roundtrip(self, manager):
        encrypted = manager.encrypt("secret data")
        assert encrypted != "secret data"
        decrypted = manager.decrypt(encrypted)
        assert decrypted == "secret data"

    def test_encrypt_dict(self, manager):
        encrypted = manager.encrypt_dict({"key1": "val1", "key2": "val2"})
        assert encrypted["key1"] != "val1"
        assert encrypted["key2"] != "val2"

    def test_decrypt_dict(self, manager):
        encrypted = manager.encrypt_dict({"key1": "val1", "key2": "val2"})
        decrypted = manager.decrypt_dict(encrypted)
        assert decrypted["key1"] == "val1"
        assert decrypted["key2"] == "val2"

    def test_decrypt_dict_invalid_value(self, manager):
        result = manager.decrypt_dict({"key1": "invalid_encrypted_data"})
        # Should keep original if decryption fails
        assert "key1" in result

    def test_sign_and_verify(self, manager):
        sig = manager.sign("message")
        assert manager.verify("message", sig) is True
        assert manager.verify("other", sig) is False

    def test_sign_string_key(self):
        manager = CryptoManager(encryption_key="my-secret")
        sig = manager.sign("message")
        assert manager.verify("message", sig) is True

    def test_rotate_key(self, manager):
        new_key = CryptoManager.generate_encryption_key()
        manager.rotate_key(new_key)
        assert manager._encryption_key == new_key

    def test_hash_method(self):
        assert CryptoManager.hash("data", "sha256") == hash_sha256("data")
        assert CryptoManager.hash("data", "sha512") == hash_sha512("data")
        assert CryptoManager.hash("data", "md5") == hash_sha256("data")
        assert CryptoManager.hash("data", "unknown") == hash_sha256("data")

    def test_generate_token_method(self):
        token = CryptoManager.generate_token(length=16, prefix="test_")
        assert token.startswith("test_")

    def test_generate_encryption_key(self):
        key = CryptoManager.generate_encryption_key()
        assert len(key) == 44  # Fernet key length

    def test_missing_encryption_key(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENCRYPTION_KEY", None)
            with pytest.raises(ValueError, match="Encryption key required"):
                CryptoManager()

    def test_encrypt_api_key_with_env_key(self):
        key = CryptoManager.generate_encryption_key()
        with patch.dict(os.environ, {"ENCRYPTION_KEY": key}):
            encrypted = encrypt_api_key("sk-test")
            assert encrypted != "sk-test"
            decrypted = decrypt_api_key(encrypted)
            assert decrypted == "sk-test"

    def test_decrypt_api_key_missing_key(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENCRYPTION_KEY", None)
            with pytest.raises(ValueError, match="Encryption key required"):
                decrypt_api_key("encrypted")

    def test_encrypt_api_key_no_env_key(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENCRYPTION_KEY", None)
            with pytest.raises(ValueError, match="Encryption key required"):
                encrypt_api_key("sk-test")

    def test_encrypt_api_key_with_short_key(self):
        # Short key should still work (derived from SHA-256)
        encrypted = encrypt_api_key("sk-test", encryption_key="short")
        decrypted = decrypt_api_key(encrypted, encryption_key="short")
        assert decrypted == "sk-test"

    def test_encrypt_api_key_with_bytes_key(self):
        encrypted = encrypt_api_key("sk-test", encryption_key=b"bytes-key-12345")
        decrypted = decrypt_api_key(encrypted, encryption_key=b"bytes-key-12345")
        assert decrypted == "sk-test"

    def test_signing_key_defaults_to_encryption_key(self):
        key = CryptoManager.generate_encryption_key()
        manager = CryptoManager(encryption_key=key)
        assert manager._signing_key == key

    def test_custom_signing_key(self):
        enc_key = CryptoManager.generate_encryption_key()
        manager = CryptoManager(encryption_key=enc_key, signing_key="custom-signing-key")
        assert manager._signing_key == "custom-signing-key"
