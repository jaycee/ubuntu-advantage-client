import logging
import mock
from io import BytesIO
from urllib.error import HTTPError

import pytest

from uaclient.clouds.aws import UAAutoAttachAWSInstance

M_PATH = "uaclient.clouds.aws."


class TestUAAutoAttachAWSInstance:
    @mock.patch(M_PATH + "util.readurl")
    def test_identity_doc_from_aws_url_pkcs7(self, readurl):
        """Return pkcs7 content from IMDS as AWS' identity doc"""
        readurl.return_value = "pkcs7WOOT!==", {"header": "stuff"}
        instance = UAAutoAttachAWSInstance()
        assert "pkcs7WOOT!==" == instance.identity_doc
        url = "http://169.254.169.254/latest/dynamic/instance-identity/pkcs7"
        assert [mock.call(url)] == readurl.call_args_list

    @pytest.mark.parametrize("caplog_text", [logging.DEBUG], indirect=True)
    @pytest.mark.parametrize("fail_count,exception", ((3, False), (4, True)))
    @mock.patch(M_PATH + "util.time.sleep")
    @mock.patch(M_PATH + "util.readurl")
    def test_retry_backoff_on_failed_identity_doc(
        self, readurl, sleep, fail_count, exception, caplog_text
    ):
        """Retry backoff is attempted before failing to get AWS.identity_doc"""

        def fake_someurlerrors(url):
            if readurl.call_count <= fail_count:
                raise HTTPError(
                    "http://me",
                    700 + readurl.call_count,
                    "funky error msg",
                    None,
                    BytesIO(),
                )
            return "pkcs7WOOT!==", {"header": "stuff"}

        readurl.side_effect = fake_someurlerrors
        instance = UAAutoAttachAWSInstance()
        if exception:
            with pytest.raises(HTTPError) as excinfo:
                instance.identity_doc
            assert 704 == excinfo.value.code
        else:
            assert "pkcs7WOOT!==" == instance.identity_doc

        expected_sleep_calls = [mock.call(1), mock.call(2), mock.call(5)]
        assert expected_sleep_calls == sleep.call_args_list
        expected_logs = [
            "HTTP Error 701: funky error msg Retrying 3 more times.",
            "HTTP Error 702: funky error msg Retrying 2 more times.",
            "HTTP Error 703: funky error msg Retrying 1 more times.",
        ]
        logs = caplog_text()
        for log in expected_logs:
            assert log in logs

    @pytest.mark.parametrize("uuid", ("ec2", "ec2yep"))
    @mock.patch(M_PATH + "util.load_file")
    def test_is_viable_based_on_sys_hypervisor_uuid(self, load_file, uuid):
        """Viable ec2 platform is determined by /sys/hypervisor/uuid prefix"""
        load_file.return_value = uuid
        instance = UAAutoAttachAWSInstance()
        assert True is instance.is_viable

    @pytest.mark.parametrize(
        "hypervisor_uuid,prod_uuid,prod_serial,viable",
        (
            ("notec2", "ec2UUID", "ec2Serial", True),
            ("notec2", "EC2UUID", "Ec2Serial", True),
            ("notec2", "!EC2UUID", "Ec2Serial", False),
            ("notec2", "EC2UUID", "1Ec2Serial", False),
            ("notec2", "ec2UUID", "ec3Serial", False),
            ("notec2", "ec3UUID", "ec2Serial", False),
        ),
    )
    @mock.patch(M_PATH + "util.load_file")
    def test_is_viable_based_on_sys_product_serial_and_uuid(
        self, load_file, hypervisor_uuid, prod_uuid, prod_serial, viable
    ):
        """Platform is viable when product serial and uuid start with ec2"""

        def fake_load_file(f_name):
            if f_name == "/sys/hypervisor/uuid":
                return hypervisor_uuid
            if f_name == "/sys/class/dmi/id/product_uuid":
                return prod_uuid
            if f_name == "/sys/class/dmi/id/product_serial":
                return prod_serial
            raise AssertionError("Invalid load_file of {}".format(f_name))

        load_file.side_effect = fake_load_file
        instance = UAAutoAttachAWSInstance()
        assert viable is instance.is_viable
