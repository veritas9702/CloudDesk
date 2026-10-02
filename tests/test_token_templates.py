import json
import threading
import unittest
from urllib.parse import parse_qs, urlsplit
import httpx
from cloudtool.token_templates import TokenTemplate, PRESETS
from cloudtool.public_ip import PublicIpService, parse_public_ip
from cloudtool.models import Cancelled

class TemplateTests(unittest.TestCase):
    def test_dns_and_encoding(self):
        query = parse_qs(urlsplit(TokenTemplate('中文 &?#', PRESETS['DNS 基础']).url()).query)
        self.assertEqual(query['name'], ['中文 &?#'])
        self.assertEqual(json.loads(query['permissionGroupKeys'][0]), [{'key':'zone','type':'read'}, {'key':'dns','type':'edit'}])
        self.assertNotIn('ip', query)

    def test_edit_subsumes_read_and_deduplicates(self):
        items = TokenTemplate('test', ('zones', 'zone_write', 'zone_write')).permissions()
        self.assertEqual([(x.key, x.access) for x in items], [('zone', 'edit')])

    def test_reject_unknown_and_invalid_names(self):
        with self.assertRaises(ValueError):
            TokenTemplate('x', ('invented',)).url()
        for name in ('', 'a\nb', 'a'*101):
            with self.assertRaises(ValueError):
                TokenTemplate(name, ()).url()

    def test_public_addresses(self):
        for address in ('8.8.8.8', '2606:4700:4700::1111'):
            self.assertEqual(parse_public_ip('foo=bar\nip='+address), address)
        for value in ('ip=192.168.1.2', 'ip=127.0.0.1', 'ip=::1', 'ip=invalid', 'ip=8.8.8.8\nip=1.1.1.1', ''):
            with self.assertRaises(ValueError):
                parse_public_ip(value)

    def test_anonymous_and_no_redirect(self):
        requests = []
        def handler(request):
            requests.append(request)
            self.assertNotIn('authorization', request.headers)
            return httpx.Response(200, text='ip=8.8.8.8')
        service = PublicIpService(httpx.MockTransport(handler))
        self.assertEqual(service.detect(threading.Event()), '8.8.8.8')
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(Cancelled): service.detect(cancel)
        self.assertEqual(len(requests), 1)
        service = PublicIpService(httpx.MockTransport(lambda r: httpx.Response(302, headers={'Location':'https://example.com'})))
        with self.assertRaises(httpx.HTTPStatusError): service.detect(threading.Event())

    def test_oversize_response(self):
        service = PublicIpService(httpx.MockTransport(lambda r: httpx.Response(200, text='x'*17000)))
        with self.assertRaises(ValueError): service.detect(threading.Event())

if __name__ == '__main__': unittest.main()
