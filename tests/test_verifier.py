# tests/test_verifier.py — Unit tests for VerifierResult data model and validation
import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.verifier import VerifierResult, validate_verifier_json, _parse_verifier_output


# ─── Sample valid verifier data ──────────────────────────────────────

VALID_DONE = {
    "step_id": "S1",
    "done": True,
    "evidence": ["Browser window visible", "Desktop icons behind browser"],
    "failure_type": "NONE",
    "suggested_fix": "",
    "confidence": 0.92,
}

VALID_NOT_DONE = {
    "step_id": "S2",
    "done": False,
    "evidence": ["Address bar still shows about:blank"],
    "failure_type": "NOT_FOUND",
    "suggested_fix": "Click on the address bar first",
    "confidence": 0.75,
}


# ─── VerifierResult Tests ────────────────────────────────────────────

class TestVerifierResult:
    def test_create_done(self):
        vr = VerifierResult.from_dict(VALID_DONE)
        assert vr.step_id == "S1"
        assert vr.done is True
        assert vr.failure_type == "NONE"
        assert vr.confidence == 0.92

    def test_create_not_done(self):
        vr = VerifierResult.from_dict(VALID_NOT_DONE)
        assert vr.done is False
        assert vr.failure_type == "NOT_FOUND"

    def test_to_dict(self):
        vr = VerifierResult.from_dict(VALID_DONE)
        d = vr.to_dict()
        assert d["step_id"] == "S1"
        assert d["done"] is True

    def test_roundtrip(self):
        vr = VerifierResult.from_dict(VALID_DONE)
        restored = VerifierResult.from_dict(vr.to_dict())
        assert vr.to_dict() == restored.to_dict()


# ─── Validation Tests ────────────────────────────────────────────────

class TestValidateVerifierJson:
    def test_valid_done(self):
        validate_verifier_json(VALID_DONE)  # No exception

    def test_valid_not_done(self):
        validate_verifier_json(VALID_NOT_DONE)  # No exception

    def test_missing_step_id(self):
        data = {k: v for k, v in VALID_DONE.items() if k != "step_id"}
        with pytest.raises(ValueError, match="missing 'step_id'"):
            validate_verifier_json(data)

    def test_missing_done(self):
        data = {k: v for k, v in VALID_DONE.items() if k != "done"}
        with pytest.raises(ValueError, match="missing 'done'"):
            validate_verifier_json(data)

    def test_done_not_bool(self):
        data = {**VALID_DONE, "done": 1}
        with pytest.raises(ValueError, match="must be a boolean"):
            validate_verifier_json(data)

    def test_invalid_failure_type(self):
        data = {**VALID_DONE, "failure_type": "UNKNOWN_TYPE"}
        with pytest.raises(ValueError, match="Invalid failure_type"):
            validate_verifier_json(data)

    def test_evidence_not_list(self):
        data = {**VALID_DONE, "evidence": "not a list"}
        with pytest.raises(ValueError, match="must be a list"):
            validate_verifier_json(data)

    def test_invalid_confidence(self):
        data = {**VALID_DONE, "confidence": 2.0}
        with pytest.raises(ValueError, match="0.0-1.0"):
            validate_verifier_json(data)

    def test_not_a_dict(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            validate_verifier_json("string")


# ─── Parse Tests ─────────────────────────────────────────────────────

class TestParseVerifierOutput:
    def test_parse_clean_json(self):
        raw = json.dumps(VALID_DONE)
        vr = _parse_verifier_output(raw, "fallback")
        assert vr.step_id == "S1"
        assert vr.done is True

    def test_parse_json_with_surrounding_text(self):
        raw = "Here is my analysis:\n" + json.dumps(VALID_NOT_DONE) + "\nEnd."
        vr = _parse_verifier_output(raw, "fallback")
        assert vr.step_id == "S2"
        assert vr.done is False

    def test_parse_garbage_fallback(self):
        raw = "This is not JSON at all!"
        vr = _parse_verifier_output(raw, "S99")
        assert vr.step_id == "S99"
        assert vr.done is False
        assert vr.failure_type == "OTHER"
        assert vr.confidence == 0.1
