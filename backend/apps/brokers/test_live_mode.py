"""M13 — paper ⇄ live execution-mode switch (spec: project-plan/13-live-trading-switch.md).

These tests are the whole point of the milestone. The code they cover is inert in
production (`ENABLE_LIVE_TRADING=False`), so CI is the ONLY thing standing between
a refactor and an account that says LIVE while trading paper — or, far worse, says
PAPER while trading live.

Every assertion here is on OBSERVED BEHAVIOUR (the flag actually handed to
`TradingClient`, the error code actually raised), never on a comment or a
docstring. This codebase's recurring failure mode is a component that reports
success while doing the wrong thing; asserting on intent rather than effect is how
that keeps happening.
"""
from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings

from .alpaca.adapter import AlpacaAdapter
from .base import Account, BrokerContext
from .errors import BrokerError, BrokerErrorCode

PAPER_KEY = "PKTESTPAPERKEY123"
LIVE_KEY = "AKTESTLIVEKEY456"


def _ctx(mode: str, api_key_id: str) -> BrokerContext:
    return BrokerContext(
        account_id="acct-1",
        user_id="user-1",
        api_key_id=api_key_id,
        api_secret="secret",
        mode=mode,
    )


def _account() -> Account:
    return Account(
        account_number="TEST123",
        buying_power=Decimal("1000"),
        cash=Decimal("1000"),
    )


class BrokerContextModeTests(SimpleTestCase):
    def test_defaults_to_paper(self):
        """A caller that forgets the mode must get the SAFE one."""
        ctx = BrokerContext(account_id="a", user_id="u")
        self.assertEqual(ctx.mode, "PAPER")
        self.assertTrue(ctx.is_paper)

    def test_live_mode_is_not_paper(self):
        self.assertFalse(_ctx("LIVE", LIVE_KEY).is_paper)

    def test_repr_never_leaks_keys(self):
        r = repr(_ctx("LIVE", LIVE_KEY))
        self.assertNotIn(LIVE_KEY, r)
        self.assertNotIn("secret", r)
        self.assertIn("LIVE", r)  # mode IS safe to show, and useful in logs


class EndpointSelectionTests(SimpleTestCase):
    """AC-13-3 / AC-13-4 — the endpoint follows the ACCOUNT, not the global flag."""

    def _paper_flag_passed_to_client(self, ctx) -> bool:
        with mock.patch("alpaca.trading.client.TradingClient") as TradingClient:
            _ = AlpacaAdapter(ctx).client  # property build is the thing under test
        self.assertTrue(TradingClient.called, "adapter never constructed a client")
        return TradingClient.call_args.kwargs["paper"]

    @override_settings(ENABLE_LIVE_TRADING=False)
    def test_paper_account_uses_paper_endpoint(self):
        self.assertIs(self._paper_flag_passed_to_client(_ctx("PAPER", PAPER_KEY)), True)

    @override_settings(ENABLE_LIVE_TRADING=True)
    def test_paper_account_STAYS_paper_when_global_live_flag_is_on(self):
        """AC-13-3 — M13 F-3, the load-bearing test of this milestone.

        If someone ever "simplifies" the adapter to read the global flag, this is
        the test that fails. Turning ENABLE_LIVE_TRADING on must NOT migrate a
        single existing paper account onto the live endpoint: the flag is
        permission to create live accounts, not a mode.
        """
        self.assertIs(self._paper_flag_passed_to_client(_ctx("PAPER", PAPER_KEY)), True)

    @override_settings(ENABLE_LIVE_TRADING=True)
    def test_live_account_uses_live_endpoint(self):
        self.assertIs(self._paper_flag_passed_to_client(_ctx("LIVE", LIVE_KEY)), False)


class KeyShapeGuardTests(SimpleTestCase):
    """AC-13-5 — mode/key agreement, enforced in BOTH directions (M13 F-4)."""

    def _connect(self, ctx):
        adapter = AlpacaAdapter(ctx, client=mock.Mock())
        with mock.patch.object(AlpacaAdapter, "get_account", return_value=_account()):
            return adapter.connect()

    @override_settings(ENABLE_LIVE_TRADING=False)
    def test_live_keys_on_paper_account_rejected(self):
        """The original AC-04-6 guard. This is the one that stops a mistaken
        paste from reaching a real, funded account. It must never regress."""
        with self.assertRaises(BrokerError) as cm:
            self._connect(_ctx("PAPER", LIVE_KEY))
        self.assertEqual(cm.exception.code, BrokerErrorCode.LIVE_KEYS_FORBIDDEN)

    @override_settings(ENABLE_LIVE_TRADING=True)
    def test_live_keys_on_paper_account_still_rejected_when_live_enabled(self):
        """Enabling live trading globally must not weaken the paper guard."""
        with self.assertRaises(BrokerError) as cm:
            self._connect(_ctx("PAPER", LIVE_KEY))
        self.assertEqual(cm.exception.code, BrokerErrorCode.LIVE_KEYS_FORBIDDEN)

    @override_settings(ENABLE_LIVE_TRADING=True)
    def test_paper_keys_on_live_account_rejected(self):
        """A LIVE account holding PK keys would execute against paper while every
        screen and audit row claimed LIVE."""
        with self.assertRaises(BrokerError) as cm:
            self._connect(_ctx("LIVE", PAPER_KEY))
        self.assertEqual(cm.exception.code, BrokerErrorCode.PAPER_KEYS_ON_LIVE)

    @override_settings(ENABLE_LIVE_TRADING=True)
    def test_live_account_with_live_keys_connects_and_reports_not_paper(self):
        info = self._connect(_ctx("LIVE", LIVE_KEY))
        self.assertFalse(info.is_paper)
        self.assertEqual(info.account_number, "TEST123")

    @override_settings(ENABLE_LIVE_TRADING=False)
    def test_paper_account_with_paper_keys_connects(self):
        info = self._connect(_ctx("PAPER", PAPER_KEY))
        self.assertTrue(info.is_paper)


class MasterGateTests(SimpleTestCase):
    """The EFFECTIVE gate is `env AND db-override` (live_gate.live_trading_permitted).

    The first draft of M13 read `settings.ENABLE_LIVE_TRADING` directly here. That
    was a blocker, and — this is the important part — it was a blocker these tests
    did not catch, because they were written with `override_settings` and so only
    ever exercised the env half. A test that mirrors the implementation's mistake
    is not a test. Hence: patch the DB-override resolver, not the setting.
    """

    def _connect_live(self):
        adapter = AlpacaAdapter(_ctx("LIVE", LIVE_KEY), client=mock.Mock())
        with mock.patch.object(AlpacaAdapter, "get_account", return_value=_account()):
            return adapter.connect()

    @override_settings(ENABLE_LIVE_TRADING=False)
    def test_env_off_blocks_live(self):
        with mock.patch("apps.admin_portal.flags.is_enabled", return_value=True):
            with self.assertRaises(BrokerError) as cm:
                self._connect_live()
        self.assertEqual(cm.exception.code, BrokerErrorCode.LIVE_TRADING_DISABLED)

    @override_settings(ENABLE_LIVE_TRADING=True)
    def test_db_override_OFF_kills_live_even_though_env_is_on(self):
        """THE EMERGENCY OFF-SWITCH.

        `ENABLE_LIVE_TRADING` is registered mutable+dangerous, so an operator can
        revoke it from the admin portal with no redeploy. If the adapter reads only
        the setting, that revocation reports success and changes nothing — the
        platform keeps trading real money. This is the regression test for that.
        """
        with mock.patch("apps.admin_portal.flags.is_enabled", return_value=False):
            with self.assertRaises(BrokerError) as cm:
                self._connect_live()
        self.assertEqual(cm.exception.code, BrokerErrorCode.LIVE_TRADING_DISABLED)

    @override_settings(ENABLE_LIVE_TRADING=False)
    def test_db_override_ON_cannot_ARM_live_when_env_is_off(self):
        """The asymmetry, in the other direction: a DB write alone must never be
        able to turn real-money trading ON. Arming requires a deliberate, reviewed,
        deployed env change."""
        with mock.patch("apps.admin_portal.flags.is_enabled", return_value=True):
            with self.assertRaises(BrokerError) as cm:
                self._connect_live()
        self.assertEqual(cm.exception.code, BrokerErrorCode.LIVE_TRADING_DISABLED)

    @override_settings(ENABLE_LIVE_TRADING=True)
    def test_both_on_permits_live(self):
        with mock.patch("apps.admin_portal.flags.is_enabled", return_value=True):
            info = self._connect_live()
        self.assertFalse(info.is_paper)


class StreamModeTests(SimpleTestCase):
    """The fill stream MUST follow the account's mode (M13 F-3).

    A LIVE account whose stream subscribed to the PAPER socket would place real
    orders and never see a single fill — while `broker_stream_heartbeat_age_seconds`
    stayed fresh, so `BrokerStreamSilent` would never fire. Positions, P&L and the
    kill switch would all then be reasoning about a portfolio that does not exist.
    """

    def _paper_flag_passed_to_stream(self, ctx) -> bool:
        from .alpaca.streams import AlpacaStream

        with mock.patch("alpaca.trading.stream.TradingStream") as TradingStream:
            AlpacaStream(ctx, on_event=lambda *a: None)._build_stream()
        self.assertTrue(TradingStream.called, "stream was never constructed")
        return TradingStream.call_args.kwargs["paper"]

    @override_settings(ENABLE_LIVE_TRADING=False)
    def test_paper_account_streams_paper(self):
        self.assertIs(self._paper_flag_passed_to_stream(_ctx("PAPER", PAPER_KEY)), True)

    @override_settings(ENABLE_LIVE_TRADING=True)
    def test_live_account_streams_LIVE_not_paper(self):
        with mock.patch("apps.admin_portal.flags.is_enabled", return_value=True):
            self.assertIs(self._paper_flag_passed_to_stream(_ctx("LIVE", LIVE_KEY)), False)

    @override_settings(ENABLE_LIVE_TRADING=True)
    def test_live_stream_refused_when_override_revokes_permission(self):
        from .alpaca.streams import AlpacaStream

        with mock.patch("apps.admin_portal.flags.is_enabled", return_value=False):
            with self.assertRaises(BrokerError) as cm:
                AlpacaStream(_ctx("LIVE", LIVE_KEY), on_event=lambda *a: None)._build_stream()
        self.assertEqual(cm.exception.code, BrokerErrorCode.LIVE_TRADING_DISABLED)


class SupervisorContextTests(SimpleTestCase):
    """AC-13-11, the half that a naive test misses.

    `StreamModeTests` above hands `_build_stream()` a context it built itself — so
    it would keep passing even if the supervisor never propagated `mode` at all,
    and the live fill stream would still be silently paper in production.

    THE ENDPOINT IS ONLY AS CORRECT AS THE CONTEXT THAT REACHES IT. So assert the
    real construction path: StreamSupervisor._context_for(account).
    """

    def _context_for(self, mode: str):
        from .streams import StreamSupervisor

        account = mock.Mock()
        account.id = "acct-1"
        account.user_id = "user-1"
        account.account_number = "X1"
        account.mode = mode
        account.api_key_id_enc = b""
        account.api_secret_enc = b""

        with mock.patch("apps.brokers.streams.decrypt_key", return_value="k"):
            return StreamSupervisor()._context_for(account)

    def test_supervisor_propagates_live_mode(self):
        ctx = self._context_for("LIVE")
        self.assertEqual(ctx.mode, "LIVE")
        self.assertFalse(ctx.is_paper, "supervisor dropped mode → live stream would be PAPER")

    def test_supervisor_propagates_paper_mode(self):
        ctx = self._context_for("PAPER")
        self.assertTrue(ctx.is_paper)


class AccountDtoModeTests(SimpleTestCase):
    """`get_account()` must not claim to be paper while running live.

    `_call()` writes a BrokerCallAudit row, so the audit sink is patched out —
    SimpleTestCase has no DB, and the audit trail is not what is under test here.
    """

    def _get_account(self, ctx):
        client = mock.Mock()
        client.get_account.return_value = mock.Mock(
            account_number="X1",
            buying_power="10",
            cash="10",
            currency="USD",
            status="ACTIVE",
            equity="10",
            last_equity="10",
        )
        with mock.patch("apps.brokers.alpaca.adapter.record_broker_call"):
            return AlpacaAdapter(ctx, client=client).get_account()

    @override_settings(ENABLE_LIVE_TRADING=True)
    def test_get_account_reports_live(self):
        with mock.patch("apps.admin_portal.flags.is_enabled", return_value=True):
            acct = self._get_account(_ctx("LIVE", LIVE_KEY))
        self.assertFalse(acct.is_paper)

    def test_get_account_reports_paper(self):
        acct = self._get_account(_ctx("PAPER", PAPER_KEY))
        self.assertTrue(acct.is_paper)
