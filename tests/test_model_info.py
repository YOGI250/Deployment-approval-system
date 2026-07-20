"""
test_model_info.py

IMP-002: verifies get_model_info() and GET /model-info -- the Model
Information dashboard panel's data source. The core rule under test is
"never fabricate": every field is either a real value read from the
model artifact/metadata file/filesystem, or the literal string "N/A".
"""

import os
import sys
import json
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["API_KEY"] = "test-secret-123"

import pytest
from fastapi.testclient import TestClient

import model_info
import api
importlib.reload(api)

client = TestClient(api.app)


class FakeModel:
    def __init__(self, n_features_in_=None, feature_names_in_=None):
        if n_features_in_ is not None:
            self.n_features_in_ = n_features_in_
        if feature_names_in_ is not None:
            self.feature_names_in_ = feature_names_in_


class TestMetadataExists:
    """When data/model_metadata.json exists with real values, they must
    be surfaced exactly -- not recomputed, not rounded away."""

    def test_training_dataset_size_read_from_metadata_file(self, monkeypatch, tmp_path):
        metadata_file = tmp_path / "model_metadata.json"
        metadata_file.write_text(json.dumps({"training_dataset_size": 500}))
        monkeypatch.setattr(model_info, "METADATA_PATH", str(metadata_file))
        monkeypatch.setattr(model_info, "_get_model", lambda: FakeModel(n_features_in_=9))

        result = model_info.get_model_info()
        assert result["training_dataset_size"] == 500

    def test_offline_validation_accuracy_read_from_metadata_file(self, monkeypatch, tmp_path):
        metadata_file = tmp_path / "model_metadata.json"
        metadata_file.write_text(json.dumps({"offline_validation_accuracy": 0.87}))
        monkeypatch.setattr(model_info, "METADATA_PATH", str(metadata_file))
        monkeypatch.setattr(model_info, "_get_model", lambda: FakeModel(n_features_in_=9))

        result = model_info.get_model_info()
        assert result["offline_validation_accuracy"] == 0.87

    def test_malformed_metadata_file_does_not_crash(self, monkeypatch, tmp_path):
        """A corrupt sidecar file must degrade to N/A, never raise."""
        metadata_file = tmp_path / "model_metadata.json"
        metadata_file.write_text("{ this is not valid json")
        monkeypatch.setattr(model_info, "METADATA_PATH", str(metadata_file))
        monkeypatch.setattr(model_info, "_get_model", lambda: FakeModel(n_features_in_=9))

        result = model_info.get_model_info()
        assert result["training_dataset_size"] == "N/A"
        assert result["offline_validation_accuracy"] == "N/A"


class TestMetadataMissing:
    """This repo ships no data/model_metadata.json today -- confirms the
    honest, expected default: N/A, never a guessed number."""

    def test_no_metadata_file_yields_na_for_both_fields(self, monkeypatch, tmp_path):
        nonexistent = tmp_path / "does_not_exist.json"
        monkeypatch.setattr(model_info, "METADATA_PATH", str(nonexistent))
        monkeypatch.setattr(model_info, "_get_model", lambda: FakeModel(n_features_in_=9))

        result = model_info.get_model_info()
        assert result["training_dataset_size"] == "N/A"
        assert result["offline_validation_accuracy"] == "N/A"

    def test_model_load_failure_yields_na_features_not_a_crash(self, monkeypatch, tmp_path):
        nonexistent = tmp_path / "does_not_exist.json"
        monkeypatch.setattr(model_info, "METADATA_PATH", str(nonexistent))

        def raise_file_not_found():
            raise FileNotFoundError("model.pkl not found")

        monkeypatch.setattr(model_info, "_get_model", raise_file_not_found)

        result = model_info.get_model_info()
        assert result["number_of_features"] == "N/A"
        # unaffected fields still resolve normally
        assert result["model_name"] == model_info.MODEL_NAME

    def test_missing_model_file_yields_na_last_updated(self, monkeypatch, tmp_path):
        monkeypatch.setattr(model_info, "MODEL_PATH", str(tmp_path / "no_such_model.pkl"))
        result = model_info.get_model_info()
        assert result["model_last_updated"] == "N/A"


class TestNumberOfFeatures:
    def test_prefers_feature_names_in_when_present(self):
        model = FakeModel(n_features_in_=9, feature_names_in_=["a", "b", "c"])
        assert model_info._number_of_features(model) == 3

    def test_falls_back_to_n_features_in_when_names_absent(self):
        """The real trained model in this repo was fit on plain lists, not
        a named DataFrame -- feature_names_in_ is genuinely absent, so this
        is the path actually exercised in production."""
        model = FakeModel(n_features_in_=9)
        assert model_info._number_of_features(model) == 9

    def test_neither_attribute_present_yields_na(self):
        model = object()
        assert model_info._number_of_features(model) == "N/A"


class TestRealModelArtifact:
    """Sanity check against the actual data/model.pkl shipped in this repo."""

    def test_real_model_info_never_fabricates(self):
        result = model_info.get_model_info()
        assert result["model_name"] == "RandomForest"
        assert result["model_version"] == "1.0"
        assert result["prompt_version"]  # reused from risk_scorer, non-empty
        # 10 features since team_recent_success_rate was added alongside
        # author_recent_success_rate -- update this if FEATURE_ORDER changes again.
        assert result["number_of_features"] == 10
        # No metadata file ships in this repo -- both must be honest N/A.
        assert result["training_dataset_size"] == "N/A"
        assert result["offline_validation_accuracy"] == "N/A"
        # Real file exists -- must be a real timestamp, not N/A.
        assert result["model_last_updated"] != "N/A"


class TestModelInfoEndpoint:
    def test_endpoint_returns_200_and_expected_keys(self):
        response = client.get("/model-info")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
            "model_name", "model_version", "prompt_version",
            "training_dataset_size", "number_of_features",
            "offline_validation_accuracy", "model_last_updated",
        }

    def test_endpoint_is_unauthenticated_like_health(self):
        """Matches / and /health -- model metadata isn't deployment data,
        so pipelines/dashboards shouldn't need a secret to read it."""
        response = client.get("/model-info")
        assert response.status_code == 200


class TestDashboardCompatibility:
    """dashboard.py can't be imported directly (it runs Streamlit calls at
    import time) -- this confirms the exact dict shape it depends on."""

    def test_result_has_exact_expected_keys(self):
        result = model_info.get_model_info()
        assert set(result.keys()) == {
            "model_name", "model_version", "prompt_version",
            "training_dataset_size", "number_of_features",
            "offline_validation_accuracy", "model_last_updated",
        }

    def test_every_field_is_present_and_never_none(self):
        """dashboard.py's model_metric_value() treats None as a bug
        signal, not an expected value -- missing data must be "N/A", not None."""
        result = model_info.get_model_info()
        for key, value in result.items():
            assert value is not None, f"{key} was None instead of 'N/A'"


class TestBackwardCompatibility:
    """IMP-002 must not disturb any existing endpoint or module."""

    def test_predict_endpoint_still_present(self):
        assert any(route.path == "/predict" for route in api.app.routes)

    def test_health_endpoint_unaffected(self):
        response = client.get("/health")
        assert response.status_code in (200, 503)
        assert "status" in response.json()

    def test_deployment_verification_endpoint_unaffected(self):
        paths = {route.path for route in api.app.routes}
        assert "/deployment-verification" in paths

    def test_history_endpoint_unaffected(self):
        paths = {route.path for route in api.app.routes}
        assert "/history" in paths

    def test_no_existing_endpoint_removed(self):
        paths = {route.path for route in api.app.routes}
        assert {"/", "/health", "/predict", "/history", "/outcome",
                "/deployment-verification", "/model-info"}.issubset(paths)
