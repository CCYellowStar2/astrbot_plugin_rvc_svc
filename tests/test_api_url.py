import os
import unittest

from api_url import prepare_api_url


class ApiUrlTests(unittest.TestCase):
    def setUp(self):
        self._environment = {name: os.environ.get(name) for name in ("NO_PROXY", "no_proxy")}
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"
        os.environ["no_proxy"] = "localhost,127.0.0.1"

    def tearDown(self):
        for name, value in self._environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_prepares_host_docker_url_for_direct_access(self):
        url = prepare_api_url("http://host.docker.internal:7860/\u2060")

        self.assertEqual(url, "http://host.docker.internal:7860/")
        self.assertIn("host.docker.internal", os.environ["NO_PROXY"].split(","))
        self.assertIn("host.docker.internal", os.environ["no_proxy"].split(","))


if __name__ == "__main__":
    unittest.main()
