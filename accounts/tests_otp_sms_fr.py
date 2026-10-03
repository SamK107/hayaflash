"""SMS OTP en francais."""

from __future__ import annotations

from unittest import mock

from orders.tests import LiveFlashSaleProductFixture


class OtpSmsFrenchTests(LiveFlashSaleProductFixture):
    def test_otp_sms_is_french(self) -> None:
        from accounts.services import otp

        with mock.patch("accounts.services.sms.send_sms") as send:
            otp.send_otp(self.buyer.phone)
        send.assert_called_once()
        body = send.call_args[0][1]
        self.assertTrue(body.startswith("Votre code de vérification HayaFlash : "), body)
        self.assertNotIn("Your verification", body)
