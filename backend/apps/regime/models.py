"""Regime models (M06 §8).

- ``FeatureVectorSnapshot`` — the standardized feature vector at a timestamp,
  plus a content hash for reproducibility (AC-06-10).
- ``HMMModel`` — a trained Gaussian HMM (params serialized JSON), with a state→
  label map, holdout log-likelihood, and an ``active`` swap flag (AC-06-4).
- ``RegimeObservation`` — the rule + HMM + ensemble output at a timestamp,
  persisted for the history chart and downstream consumers (M08 sizing).
"""
from __future__ import annotations

from django.db import models


class FeatureVectorSnapshot(models.Model):
    id = models.BigAutoField(primary_key=True)
    scope = models.CharField(max_length=16, default="MARKET", db_index=True)
    ts = models.DateTimeField(db_index=True)
    features = models.JSONField(default=dict)  # standardized (z-scored) vector
    raw_features = models.JSONField(default=dict)  # pre-standardization
    content_hash = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "regime_feature_snapshot"
        unique_together = ("scope", "ts")
        indexes = [models.Index(fields=["scope", "-ts"])]

    def __str__(self) -> str:
        return f"FeatureVectorSnapshot<{self.scope} {self.ts:%Y-%m-%d %H:%M}>"


class HMMModel(models.Model):
    id = models.BigAutoField(primary_key=True)
    version = models.CharField(max_length=48, unique=True)  # trained_at iso
    n_states = models.PositiveSmallIntegerField(default=4)
    params = models.JSONField(default=dict)  # startprob, transmat, means, covars
    state_labels = models.JSONField(default=dict)  # {"0":"BULL", ...}
    train_ll = models.FloatField(null=True, blank=True)
    holdout_ll = models.FloatField(null=True, blank=True)
    active = models.BooleanField(default=False, db_index=True)
    trained_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "regime_hmm_model"
        indexes = [models.Index(fields=["active", "-trained_at"])]

    def __str__(self) -> str:
        return f"HMMModel<{self.version} active={self.active} ll={self.holdout_ll}>"


class RegimeObservation(models.Model):
    class Scope(models.TextChoices):
        MARKET = "MARKET", "Market"

    id = models.BigAutoField(primary_key=True)
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.MARKET, db_index=True)
    ts = models.DateTimeField(db_index=True)
    label = models.CharField(max_length=16)  # ensemble label
    rule_bucket = models.CharField(max_length=16)  # RISK_ON/NEUTRAL/RISK_OFF/PANIC
    rule_score = models.FloatField(default=0.0)
    hmm_state = models.CharField(max_length=16, blank=True, default="")
    hmm_probs = models.JSONField(default=dict)
    top_features = models.JSONField(default=list)
    model_version = models.CharField(max_length=48, blank=True, default="")
    model_degraded = models.BooleanField(default=False)
    ensemble_version = models.CharField(max_length=16, default="v1")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "regime_observation"
        unique_together = ("scope", "ts")
        indexes = [models.Index(fields=["scope", "-ts"])]

    def __str__(self) -> str:
        return f"RegimeObservation<{self.scope} {self.ts:%Y-%m-%d %H:%M} {self.label}>"
