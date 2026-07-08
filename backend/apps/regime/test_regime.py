"""M06 — regime: rule classifier, ensemble, HMM, features, services, API."""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

import numpy as np
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.m04_testutils import auth_headers, create_user
from apps.regime import ensemble, features, hmm_model, rule_classifier
from apps.regime.hmm_model import FEATURE_ORDER
from apps.regime.models import FeatureVectorSnapshot, HMMModel, RegimeObservation
from apps.regime.services import activate_model, compute_observation


# ---------------------------------------------------------------------------
# Rule classifier
# ---------------------------------------------------------------------------
class RuleClassifierTests(TestCase):
    def test_risk_on(self):
        feats = {"pct_above_50sma": 2.5, "pct_above_200sma": 2.0, "mom_50": 2.0,
                 "mom_200": 2.0, "vix": -2.0, "hy_oas": -2.0}
        r = rule_classifier.classify(feats)
        self.assertEqual(r.bucket, "RISK_ON")
        self.assertGreaterEqual(r.score, 70)

    def test_panic(self):
        feats = {"vix": 4.0, "hy_oas": 4.0, "move": 4.0, "pct_above_50sma": -3.0, "mom_50": -3.0}
        r = rule_classifier.classify(feats)
        self.assertEqual(r.bucket, "PANIC")
        self.assertLess(r.score, 30)

    def test_neutral_and_top_features(self):
        r = rule_classifier.classify({})  # all zero → 50 → NEUTRAL
        self.assertEqual(r.bucket, "NEUTRAL")
        self.assertEqual(r.score, 50.0)
        r2 = rule_classifier.classify({"vix": 3.0, "pct_above_50sma": 1.0})
        names = [t["name"] for t in r2.top_features]
        self.assertIn("vix", names)

    @override_settings(REGIME_RULE_WEIGHTS={"vix": -10.0})
    def test_weight_override(self):
        r = rule_classifier.classify({"vix": 2.0})
        self.assertLess(r.score, 50)


# ---------------------------------------------------------------------------
# Ensemble
# ---------------------------------------------------------------------------
class EnsembleTests(TestCase):
    def test_decision_table(self):
        self.assertEqual(ensemble.decide("PANIC", None, None), "CRISIS")
        self.assertEqual(ensemble.decide("RISK_ON", "BULL", 0.9), "BULL")
        self.assertEqual(ensemble.decide("RISK_ON", "CHOP", 0.8), "CHOP")
        self.assertEqual(ensemble.decide("RISK_ON", "CHOP", 0.6), "NEUTRAL")
        self.assertEqual(ensemble.decide("RISK_OFF", "BEAR", 0.5), "BEAR")
        self.assertEqual(ensemble.decide("RISK_OFF", "CHOP", 0.5), "BEAR")
        self.assertEqual(ensemble.decide("NEUTRAL", "BULL", 0.9), "BULL")
        self.assertEqual(ensemble.decide("NEUTRAL", "BEAR", 0.9), "BEAR")
        self.assertEqual(ensemble.decide("NEUTRAL", None, None), "NEUTRAL")  # rule fallback

    def test_deterministic(self):
        a = ensemble.decide("RISK_ON", "CHOP", 0.75)
        b = ensemble.decide("RISK_ON", "CHOP", 0.75)
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# Features (reproducibility)
# ---------------------------------------------------------------------------
class FeatureTests(TestCase):
    def _inputs(self):
        rng = list(range(1, 260))
        return {
            "spy_closes": [100 + i * 0.1 for i in rng],
            "vix": 15.0, "vix3m": 17.0, "move": 90.0, "hy_oas": 3.5, "ig_oas": 1.2,
            "y10": 4.2, "y2": 4.0, "dxy": 103.0,
            "constituents": {f"S{i}": [50 + j * 0.05 for j in rng] for i in range(10)},
        }

    def test_reproducible(self):
        raw1 = features.compute_raw_features(self._inputs())
        raw2 = features.compute_raw_features(self._inputs())
        self.assertEqual(raw1, raw2)
        self.assertEqual(features.content_hash(raw1), features.content_hash(raw2))

    def test_standardize_clip(self):
        raw = {k: 0.0 for k in FEATURE_ORDER}
        raw["vix"] = 1000.0
        hist = {"vix": [10.0, 11.0, 9.0, 10.5]}
        std = features.standardize(raw, hist)
        self.assertLessEqual(std["vix"], 4.0)
        self.assertGreaterEqual(std["vix"], -4.0)

    def test_feature_vector_has_all_keys(self):
        raw = features.compute_raw_features({"spy_closes": [1, 2, 3]})
        self.assertEqual(set(raw.keys()), set(FEATURE_ORDER))


# ---------------------------------------------------------------------------
# HMM
# ---------------------------------------------------------------------------
def _synthetic_matrix(n=200, seed=1):
    rng = np.random.default_rng(seed)
    # two clusters (calm vs stressed) in 15-dim
    a = rng.normal(0.5, 0.3, size=(n // 2, len(FEATURE_ORDER)))
    b = rng.normal(-0.5, 0.5, size=(n - n // 2, len(FEATURE_ORDER)))
    return np.vstack([a, b])


class HMMTests(TestCase):
    def test_train_deterministic(self):
        X = _synthetic_matrix()
        _m1, ll1 = hmm_model.train_hmm(X, n_restarts=3, seed=7)
        _m2, ll2 = hmm_model.train_hmm(X, n_restarts=3, seed=7)
        self.assertAlmostEqual(ll1, ll2, places=4)

    def test_serialize_roundtrip_and_decode(self):
        X = _synthetic_matrix()
        model, _ll = hmm_model.train_hmm(X, n_restarts=3, seed=7)
        labels = hmm_model.label_states(model)
        params = hmm_model.serialize_model(model, labels)
        restored = hmm_model.deserialize_model(params)
        state, probs = hmm_model.decode_current(restored, X)
        self.assertEqual(len(probs), 4)
        self.assertAlmostEqual(sum(probs), 1.0, places=3)
        seq = hmm_model.viterbi_sequence(restored, X[-20:])
        self.assertEqual(len(seq), 20)

    def test_label_states_covers_four(self):
        X = _synthetic_matrix()
        model, _ = hmm_model.train_hmm(X, n_restarts=3, seed=7)
        labels = hmm_model.label_states(model)
        self.assertEqual(set(labels.values()), {"BULL", "CHOP", "BEAR", "CRISIS"})


# ---------------------------------------------------------------------------
# Services + retrain
# ---------------------------------------------------------------------------
class ServiceTests(TestCase):
    def test_compute_observation_rule_only_when_no_model(self):
        std = {"pct_above_50sma": 2.5, "vix": -2.0, "mom_50": 2.0}
        obs = compute_observation(ts=timezone.now(), std_features=std)
        self.assertTrue(obs.model_degraded)  # no active model
        self.assertEqual(obs.label, "BULL")  # rule RISK_ON → BULL fallback

    def test_activate_model_swap_guard(self):
        old = HMMModel.objects.create(version="old", holdout_ll=-100.0, trained_at=timezone.now(), active=True)
        worse = HMMModel.objects.create(version="worse", holdout_ll=-200.0, trained_at=timezone.now())
        self.assertFalse(activate_model(worse))  # regression rejected
        self.assertTrue(HMMModel.objects.get(pk=old.pk).active)
        better = HMMModel.objects.create(version="better", holdout_ll=-90.0, trained_at=timezone.now())
        self.assertTrue(activate_model(better))
        self.assertFalse(HMMModel.objects.get(pk=old.pk).active)

    def test_retrain_task_trains_and_activates(self):
        rng = np.random.default_rng(3)
        for i in range(160):
            vec = rng.normal(0, 1, size=len(FEATURE_ORDER))
            FeatureVectorSnapshot.objects.create(
                scope="MARKET", ts=timezone.now() - timedelta(days=160 - i),
                features={k: float(v) for k, v in zip(FEATURE_ORDER, vec, strict=True)},
                content_hash=f"h{i}",
            )
        from apps.regime.tasks import retrain_hmm

        result = retrain_hmm()
        self.assertIn("version", result)
        self.assertTrue(HMMModel.objects.filter(active=True).exists())

    def test_activate_rescores_incumbent_on_new_holdout(self):
        # FIX-M9: the incumbent must be RESCORED on the candidate's holdout window
        # (its stored LL came from a different window and isn't comparable).
        from apps.regime.hmm_model import (
            deserialize_model,
            label_states,
            serialize_model,
            train_hmm,
        )

        X = _synthetic_matrix(n=200, seed=11)
        model, _ = train_hmm(X, n_restarts=3, seed=11)
        params = serialize_model(model, label_states(model))
        current = HMMModel.objects.create(
            version="cur", params=params, holdout_ll=-9_999.0,  # bogus stored LL
            trained_at=timezone.now(), active=True,
        )
        hold_X = _synthetic_matrix(n=60, seed=12)
        current_ll = float(deserialize_model(params).score(hold_X))
        margin = abs(current_ll) * 0.05 + 10  # clear the within-1% band

        worse = HMMModel.objects.create(version="worse", holdout_ll=current_ll - margin,
                                        trained_at=timezone.now())
        self.assertFalse(activate_model(worse, hold_X=hold_X))          # rejected vs RESCORED LL
        self.assertTrue(HMMModel.objects.get(pk=current.pk).active)

        better = HMMModel.objects.create(version="better", holdout_ll=current_ll + margin,
                                         trained_at=timezone.now())
        self.assertTrue(activate_model(better, hold_X=hold_X))
        self.assertFalse(HMMModel.objects.get(pk=current.pk).active)


# ---------------------------------------------------------------------------
# Missing-input degradation (FIX-M13) + daily pipeline (FIX-H10)
# ---------------------------------------------------------------------------
class MissingInputDegradationTests(TestCase):
    def test_missing_stress_inputs_neutralize_not_risk_on(self):
        # A history where VIX/HY vary (non-zero sd) so a fabricated raw 0 would
        # z-score strongly negative and (negative weights) pin the score RISK_ON.
        vix_hist = [15.0 + (i % 10) for i in range(250)]
        hy_hist = [3.0 + (i % 5) * 0.5 for i in range(250)]
        history = {"vix": vix_hist, "hy_oas": hy_hist}
        inputs = {"spy_closes": [100.0] * 60}  # no vix / hy_oas / move / ig_oas
        raw = features.compute_raw_features(inputs)
        missing = features.missing_critical_inputs(inputs)
        self.assertIn("vix", missing)
        self.assertIn("hy_oas", missing)

        # Old behavior: fabricated 0 → strong negative z → RISK_ON (the bug).
        std_bug = features.standardize(raw, history)
        self.assertEqual(rule_classifier.classify(std_bug).bucket, "RISK_ON")
        # Fixed: missing inputs neutralize → not RISK_ON.
        std_fixed = features.standardize(
            raw, history, neutral_keys=features.neutral_feature_keys(missing)
        )
        self.assertEqual(std_fixed["vix"], 0.0)
        self.assertEqual(std_fixed["hy_oas"], 0.0)
        self.assertNotEqual(rule_classifier.classify(std_fixed).bucket, "RISK_ON")

        obs = compute_observation(ts=timezone.now(), std_features=std_fixed, data_degraded=bool(missing))
        self.assertTrue(obs.model_degraded)
        self.assertNotEqual(obs.label, "BULL")


class DailyPipelineTests(TestCase):
    def _inputs(self):
        rng = list(range(1, 60))
        return {
            "spy_closes": [100 + i * 0.1 for i in rng],
            "vix": 15.0, "hy_oas": 3.5, "ig_oas": 1.2, "y10": 4.2, "y2": 4.0, "dxy": 103.0,
        }

    def test_pipeline_produces_snapshot_and_observation(self):
        # FIX-H10: with fixture inputs injected, one run produces both rows.
        from apps.regime.tasks import run_daily_feature_pipeline

        res = run_daily_feature_pipeline(inputs=self._inputs())
        self.assertTrue(FeatureVectorSnapshot.objects.filter(id=res["snapshot"]).exists())
        self.assertTrue(RegimeObservation.objects.filter(id=res["observation"]).exists())

    def test_no_source_configured_skips_without_error(self):
        from apps.regime.tasks import compute_features_daily

        with override_settings(FMP_API_KEY="", FRED_API_KEY=""):
            res = compute_features_daily()
        self.assertEqual(res.get("skipped"), "no_market_data_source_configured")

    def test_source_configured_runs_pipeline(self):
        # FIX-H10: the guard is a real key check, not an unconditional stub — with
        # keys present the task runs the pipeline (inputs stubbed, no live calls).
        from apps.regime import tasks

        with override_settings(FMP_API_KEY="k", FRED_API_KEY="k"), \
             mock.patch.object(tasks, "gather_daily_inputs", return_value=self._inputs()):
            res = tasks.compute_features_daily()
        self.assertIn("snapshot", res)
        self.assertTrue(RegimeObservation.objects.filter(id=res["observation"]).exists())


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class RegimeApiTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_current(self):
        RegimeObservation.objects.create(
            scope="MARKET", ts=timezone.now(), label="BULL", rule_bucket="RISK_ON",
            rule_score=78.0, hmm_state="BULL", hmm_probs={"BULL": 0.8},
            top_features=[{"name": "vix", "z": -1.3}],
        )
        resp = self.client.get("/api/v1/regime/current/", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["label"], "BULL")

    def test_model_endpoint(self):
        HMMModel.objects.create(version="v1", holdout_ll=-50.0, trained_at=timezone.now(), active=True)
        resp = self.client.get("/api/v1/regime/model/", **auth_headers(self.user))
        self.assertEqual(resp.json()["data"]["version"], "v1")

    def test_symbol_501(self):
        resp = self.client.get("/api/v1/regime/symbol/AAPL/", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 501)

    def test_requires_mfa(self):
        resp = self.client.get("/api/v1/regime/current/")
        self.assertIn(resp.status_code, (401, 403))

    @override_settings(ENABLE_REGIME_UI=False)
    def test_disabled_503(self):
        resp = self.client.get("/api/v1/regime/current/", **auth_headers(self.user))
        self.assertEqual(resp.status_code, 503)
